"""Model-call sizing: how much of a document one call may carry (Run T1, 1a).

A call whose ANSWER does not fit the output limit fails as MAX_TOKENS, and
asking the same request again with the same pages fails the same way: an
eight-page list of 270 rows needs ~21k output tokens of rows alone, and the
document was failed with "no parseable response". The answer's size is
knowable before the call from the text layer (how many lines carry an
amount or a date, how many columns each row has), so the call is SIZED:

* the estimate under ``WHOLE_RATIO`` of the output limit -> one call;
* otherwise the pages are packed into groups that each fit the budget;
* a piece that still fails (MAX_TOKENS, a timeout, an unparseable answer,
  or a 400 whose cause is the request's size) is HALVED and the halves
  asked, down to one page; one page still too big is split by ROW RANGES at
  row boundaries (never inside a wrapped row);
* each later piece carries what a reader would carry over a page break:
  the table's heading line and the current group header, given as context
  that is never itself a row;
* a piece that fails at the smallest size is NAMED (its pages) and every
  other piece is kept: a truncated answer never fails a whole document.

Pure functions and one driver (`ask_adaptive`) that is handed the call as a
function, so every path is testable without a model.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

#: one call when the estimated answer is under this share of the limit
WHOLE_RATIO = 0.6

import contextvars

#: Sizing BEFORE a call is skipped while this is set - only by a replay of
#: STORED answers (tools/replay_raw.py), which can answer only the calls
#: that were recorded: one whole-document call. Halving after a FAILED call
#: is never skipped.
RECORDED_PLAN: contextvars.ContextVar = contextvars.ContextVar(
    "docagent_recorded_plan", default=False)


def presize() -> bool:
    """Is a call sized before it is made?"""
    return not RECORDED_PLAN.get()
#: a row-range piece is never smaller than this many lines
MIN_PART_LINES = 4

_DATE = re.compile(
    r"\b(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?|\d{4}-\d{2}-\d{2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2})\b",
    re.I)
_AMOUNT = re.compile(r"(?<![\w/])[-(]?[$€£¥₹]?\s?\d{1,3}(?:[,.\s]\d{3})*[.,]\d{2}\)?-?(?![\w/])")


def line_has_row_value(text: str) -> bool:
    """A line printing a date or an amount: a row, or a row's first line."""
    t = str(text or "")
    return bool(_DATE.search(t) or _AMOUNT.search(t))


def splittable_kind(resp) -> bool:
    """Would a SMALLER request plausibly succeed where this one failed?

    MAX_TOKENS, a timeout, an empty/unparseable answer: yes. A 400 only
    when the provider said the request was too big (`input_too_long`); any
    other refused request is ours to fix and asking it smaller repeats the
    error (tests/test_r4_failed_call.py). Quota, auth and policy: never."""
    import llm_contract as C
    kind = getattr(resp, "error_kind", None) if resp is not None else None
    if kind in (C.MAX_TOKENS, C.TRANSIENT, C.INVALID_JSON, C.EMPTY, C.NO_CANDIDATE):
        return True
    if kind == C.INVALID_REQUEST:
        causes = {a.get("cause") for a in (getattr(resp, "attempts", None) or [])
                  if isinstance(a, dict)}
        return "input_too_long" in causes
    return False


def output_limit(model: Optional[str] = None) -> int:
    """The largest maxOutputTokens the model takes (its profile)."""
    try:
        import llm_contract as C
        from connectors.gemini_client import model_profile
        m = model or C.setting("GEMINI_MODEL", "") or ""
        return int(model_profile(m).get("max_output") or 65536)
    except Exception:
        return 65536


def page_rows(page_text: str) -> int:
    """Lines on a page that print a date or an amount."""
    return sum(1 for ln in str(page_text or "").splitlines() if line_has_row_value(ln))


def estimate_tokens(n_fields: int, table_cols: list, rows_per_page: list,
                    pages: Optional[list] = None) -> int:
    """Expected OUTPUT tokens of one call.

    ~80 per field answer, ~300 of envelope, and per expected row
    ~60 + 20 per column of every table asked (a row answer quotes its
    source line and gives each cell). `rows_per_page` are the counts for
    the pages in this call; `table_cols` the column count of each table."""
    est = 300 + 80 * int(n_fields or 0)
    idx = range(len(rows_per_page)) if pages is None else pages
    rows = sum(int(rows_per_page[k] or 0) for k in idx if k < len(rows_per_page))
    for cols in table_cols or []:
        est += rows * (60 + 20 * int(cols or 0))
    return est


def fits_whole(est: int, limit: int, ratio: float = WHOLE_RATIO) -> bool:
    return est < ratio * limit


def pack_groups(pages: list, per_page: list, budget: float) -> list:
    """Consecutive page groups, each estimated under `budget` (a single page
    over it is a group of its own; row splitting deals with it)."""
    groups, cur, used = [], [], 0.0
    for k in pages:
        cost = float(per_page[k] if k < len(per_page) else 0)
        if cur and used + cost > budget:
            groups.append(cur)
            cur, used = [], 0.0
        cur.append(k)
        used += cost
    if cur:
        groups.append(cur)
    return groups


def row_cut(lines: list) -> Optional[int]:
    """Index at which to cut a page's text lines into two row ranges: the
    row-starting line nearest the middle. A line with no date and no amount
    (a wrapped description, a tail) is never the first line of a part, so
    a row is never cut away from its continuation. None when no cut leaves
    MIN_PART_LINES on both sides."""
    n = len(lines)
    if n < 2 * MIN_PART_LINES:
        return None
    mid = n // 2
    cands = [i for i in range(MIN_PART_LINES, n - MIN_PART_LINES + 1)
             if line_has_row_value(lines[i])]
    if not cands:
        return None
    return min(cands, key=lambda i: (abs(i - mid), i))


def carried_context(lines_before: list, heading_test: Callable[[str], bool]) -> dict:
    """What a reader carries from the lines before a cut: the table's most
    recent heading line, and the current group header (a line with no date
    and no amount directly above the first row after the last heading)."""
    heading, group = None, None
    for i, ln in enumerate(lines_before):
        s = str(ln or "").strip()
        if not s:
            continue
        if heading_test(s):
            heading, group = s, None
            continue
        if not line_has_row_value(s):
            nxt = next((str(x).strip() for x in lines_before[i + 1:] if str(x).strip()), "")
            if nxt and line_has_row_value(nxt) and len(s.split()) <= 8:
                group = s
    return {"heading": heading, "group": group}


def context_block(carry: Optional[dict]) -> str:
    """The prompt lines that hand a piece its carried state. Empty when there
    is nothing to carry, so an ordinary call's prompt is unchanged."""
    if not carry:
        return ""
    bits = []
    if carry.get("table"):
        bits.append(f'the table being read is "{carry["table"]}"')
    if carry.get("heading"):
        bits.append(f'its column headings are printed as: {carry["heading"]}')
    if carry.get("group"):
        bits.append(f'the rows continue under the group line: {carry["group"]}')
    if not bits:
        return ""
    return ("\n\nCONTEXT CARRIED FROM THE PREVIOUS PART (not rows - never return "
            "these lines as rows): " + "; ".join(bits) + ".")


def ask_adaptive(ask: Callable, pages: list, *, page_text: Callable[[int], str],
                 heading_test: Callable[[str], bool] = lambda s: False,
                 log: Callable[[str], None] = lambda s: None,
                 max_calls: int = 64) -> dict:
    """Ask for `pages` (indices), halving on a size failure.

    ``ask(pages, text=None, carry=None, part=None)`` makes ONE call and
    returns ``(parsed, resp)``; `text` replaces the single page's text for a
    row-range part. Returns ``{"pieces": [(pages, part, parsed)], "failed":
    {page index: why}, "strategy": [str], "calls": int}`` with the pieces
    in page order."""
    out = {"pieces": [], "failed": {}, "strategy": [], "calls": 0}

    def call(pg, text=None, carry=None, part=None):
        out["calls"] += 1
        return ask(pg, text=text, carry=carry, part=part)

    def why_of(resp):
        return getattr(resp, "error_kind", None) or "no usable answer"

    def lines_of(k):
        return [ln for ln in str(page_text(k) or "").splitlines()]

    def by_rows(k, lines, carry, label, depth=0):
        cut = row_cut(lines)
        if cut is None or out["calls"] >= max_calls:
            return False
        halves = [(lines[:cut], f"{label}a"), (lines[cut:], f"{label}b")]
        out["strategy"].append(f"page {k + 1}: split by rows at line {cut} of {len(lines)}")
        log(out["strategy"][-1])
        ok_all = True
        prev_lines = []
        for part_lines, name in halves:
            c = dict(carry or {})
            if prev_lines:
                c.update({key: v for key, v in carried_context(
                    prev_lines, heading_test).items() if v})
            parsed, resp = call([k], text="\n".join(part_lines), carry=c or None,
                                part=name)
            if isinstance(parsed, dict):
                out["pieces"].append(([k], name, parsed))
            elif splittable_kind(resp) and by_rows(k, part_lines, c, name, depth + 1):
                pass
            else:
                ok_all = False
                prev = out["failed"].get(k)
                out["failed"][k] = (prev + "; " if prev else "") + \
                    f"rows {name}: {why_of(resp)}"
            prev_lines = prev_lines + part_lines
        return ok_all or any(p[0] == [k] for p in out["pieces"])

    def go(pg, carry=None):
        parsed, resp = call(pg, carry=carry)
        if isinstance(parsed, dict):
            out["pieces"].append((pg, None, parsed))
            return
        if not splittable_kind(resp) or out["calls"] >= max_calls:
            for k in pg:
                out["failed"][k] = why_of(resp)
            return
        if len(pg) > 1:
            mid = len(pg) // 2
            left, right = pg[:mid], pg[mid:]
            out["strategy"].append(
                f"pages {pg[0] + 1}-{pg[-1] + 1}: {why_of(resp)} - halved into "
                f"{left[0] + 1}-{left[-1] + 1} and {right[0] + 1}-{right[-1] + 1}")
            log(out["strategy"][-1])
            go(left, carry)
            before = [ln for k in left for ln in lines_of(k)]
            c = dict(carry or {})
            c.update({key: v for key, v in carried_context(before, heading_test).items() if v})
            go(right, c or None)
            return
        k = pg[0]
        lines = lines_of(k)
        if not by_rows(k, lines, carry, "rows"):
            out["failed"].setdefault(k, why_of(resp))

    go(list(pages))
    order = {k: i for i, k in enumerate(pages)}
    out["pieces"].sort(key=lambda p: (order.get(p[0][0], 0), p[1] or ""))
    return out


def dedupe_rows(rows: list) -> list:
    """Rows merged from adjacent pieces, a row repeated at a seam kept once.

    Only a row repeated ACROSS pieces (same piece-independent content: its
    source line and its cells) is a seam duplicate; two identical rows from
    ONE piece are left for row identity to judge, as before."""
    seen, out = {}, []
    for r in rows:
        piece = r.get("_piece")
        cells = r.get("cells") if isinstance(r.get("cells"), dict) else {
            k: v for k, v in r.items() if not str(k).startswith("_") and k not in
            ("source", "page")}
        key = (re.sub(r"\s+", "", str(r.get("source") or "")).casefold(),
               tuple(sorted((str(k), str(v)) for k, v in (cells or {}).items())))
        if key[0] and key in seen and seen[key] != piece:
            continue
        seen.setdefault(key, piece)
        out.append(r)
    return out
