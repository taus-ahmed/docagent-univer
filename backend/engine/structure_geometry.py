"""Structure engine, geometry (Run T1, 3d): what the PAGE says about its own
structure, computed in code before any model is asked.

`proposal(page)` gives candidate ROWS (baseline clusters, already the
perception's lines), blocks (lines separated by vertical white space), and
for every table-like block candidate COLUMN BOUNDARIES: x-alleys no data
line's ink crosses, and right edges shared by numeric words (a right-aligned
amount column under a centred heading). The model is handed this proposal
and may confirm, merge or label it; it may not invent a boundary.

`fallback_plan(page)` turns the same geometry into a complete plan with no
model at all. It is used when no plan was asked for, when a plan fails
validation twice, and as the independent check every model plan is compared
with (3f).

Everything is decided from positions, sizes and the shapes of tokens
(a date, an amount, a colon after a label). No vocabulary.
"""
from __future__ import annotations

import re
import statistics
from typing import Optional

from perception import loose_key

_DATE = re.compile(r"(?<![\d/.-])(\d{1,2}[/.-]\d{1,2}(?:[/.-]\d{2,4})?|\d{4}-\d{2}-\d{2})(?![\d/])"
                   r"|\b[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}\b|\b\d{1,2}\s+[A-Za-z]{3,9}\.?\s+\d{4}\b")
_AMOUNT = re.compile(r"^[-(]?[$€£¥₹]?\d{1,3}(?:[,.\s]?\d{3})*(?:[.,]\d{1,2})\)?-?$|^[-(]?[$€£¥₹]\d+\)?-?$")
_NUMERIC = re.compile(r"^[-(]?[$€£¥₹]?[\d,.]+\)?-?$")
_PAGE_NO = re.compile(r"^\s*(page\s*)?\d+\s*(of|/)\s*\d+\s*$|^\s*page\s+\d+\s*$", re.I)
MARKUP = "markup (a coloured annotation over the page, not the page's own text)"
_CONT = re.compile(r"\(?\bcontinued\b\)?\s*$|\bcont'?d\b", re.I)


def is_furniture(text) -> bool:
    """A SEGMENT that is a page count (`Page 2 of 5`, `2 of 5`). A bare
    `Page 3` beside other text may be a value (`Details on: Page 3`), and a
    bare `1/2` may be a quantity: neither is furniture inside a line."""
    return bool(re.match(r"^\s*(page\s*)?\d+\s*of\s*\d+\s*$", str(text or ""), re.I))


def is_amount(tok: str) -> bool:
    t = str(tok or "").strip()
    return bool(_AMOUNT.match(t)) and any(ch.isdigit() for ch in t)


def is_numeric(tok: str) -> bool:
    t = str(tok or "").strip()
    return bool(_NUMERIC.match(t)) and any(ch.isdigit() for ch in t)


def has_date(text: str) -> bool:
    return bool(_DATE.search(str(text or "")))


# ── line features ────────────────────────────────────────────────────────────

def _words_of(page, line):
    by = page.setdefault("_by_id", {w["id"]: w for w in page["words"]})
    return [by[i] for i in line["word_ids"] if i in by]


def word_gap(page) -> float:
    """The page's ordinary gap between two words of one phrase."""
    gaps = []
    for ln in page["lines"]:
        ws = _words_of(page, ln)
        gaps += [b["x0"] - a["x1"] for a, b in zip(ws, ws[1:]) if b["x0"] > a["x1"]]
    sizes = [ln.get("size") for ln in page["lines"] if ln.get("size")]
    space = 0.35 * (statistics.median(sizes) if sizes else 10.0)
    if not gaps:
        return min(2.5, space)
    # the LOWER QUARTILE: on a table page most gaps are between columns, and
    # their median is a column gap, not the space between two words; and
    # never more than a font's own word space (~0.28 em), since a page of
    # one-word cells has no ordinary gap at all
    gaps.sort()
    return min(gaps[len(gaps) // 4], space)


def gutter(page) -> float:
    return max(6.0, 4.0 * word_gap(page))


def segments(page, line, gut=None) -> list:
    """The line cut at gaps wider than the page's gutter: [[word], ...]."""
    gut = gutter(page) if gut is None else gut
    ws = _words_of(page, line)
    out, cur = [], []
    for w in ws:
        if cur and w["x0"] - cur[-1]["x1"] > gut:
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def features(page, line, gut=None) -> dict:
    ws = _words_of(page, line)
    segs = segments(page, line, gut)
    text = line["text"]
    amounts = [w for w in ws if is_amount(w["text"])]
    nwords = len(ws)
    # a paragraph is ONE run of words: a line the gutter splits into
    # side-by-side pieces, or one carrying a date or a form widget, is
    # content laid out on the page, not prose
    widget = any(w.get("origin") == "widget" for w in ws)
    seg_texts = [" ".join(w["text"] for w in s) for s in segs]
    pair = any(re.search(r"\S:(\s|$)", t) for t in seg_texts)
    # and a `Label: value` line is a field however long its value: when in
    # doubt a line is KEPT, since a lost value is invisible
    prose = ((nwords >= 8 and text.rstrip().endswith((".", "?", "!"))) or nwords >= 12)         and len(segs) == 1 and not has_date(text) and not widget and not pair
    return {"segs": segs, "seg_texts": seg_texts, "n_amounts": len(amounts),
            "date": has_date(text), "digits": bool(re.search(r"\d", text)),
            "prose": prose and not amounts, "pair": pair, "widget": widget,
            "furniture": bool(_PAGE_NO.match(text)), "continued": bool(_CONT.search(text)),
            "nwords": nwords,
            # a reviewer's coloured annotation: every word markup, and the
            # line is no row and no label/value pair (a red amount on a
            # statement row is data, never markup)
            "markup": bool(ws) and all(w.get("markup") for w in ws)
            and not amounts and not has_date(text) and not pair and not widget}


def is_header_line(f) -> bool:
    return len(f["segs"]) >= 2 and not f["digits"] and not f["pair"] and not f["prose"]


def is_row_line(f) -> bool:
    return f["date"] or f["n_amounts"] >= 1


def starts_table(page, blk, fs, i, gut=None) -> bool:
    """Line i of a block is a table's heading line: a header-like line
    (2+ segments, no figure, no label) DIRECTLY above its rows - the next
    line (after a stacked second heading line, and at most one group or
    section line) is a row. Two header-like lines in a row: only the LOWER
    one heads the table, so an address block printed above a table
    (`Elm Row | Harbour Quay`) is never taken for its heading.
    One row is enough when its figures sit under the heading's segments
    (`Opening | Paid In` over one line of amounts)."""
    if not is_header_line(fs[i]):
        return False
    j = i + 1 + len(stacked_heads(blk, fs, i))     # stacked heading lines
    if j < len(blk) and not is_row_line(fs[j]) and not is_header_line(fs[j]) \
            and not fs[j]["prose"] and len(fs[j]["segs"]) <= 2:
        j += 1                                     # one group or section line
    if j >= len(blk) or not is_row_line(fs[j]):
        return False
    rows = sum(1 for g in fs[j:j + 5] if is_row_line(g))
    if rows >= 2:
        return True
    # one row: every figure on it sits under a heading segment
    gut = gutter(page) if gut is None else gut
    spans = [(min(w["x0"] for w in sg) - gut, max(w["x1"] for w in sg) + gut)
             for sg in fs[i]["segs"]]
    figs = [w for sg in fs[j]["segs"] for w in sg
            if is_numeric(w["text"]) or has_date(w["text"])]
    return bool(figs) and all(any(a <= (w["x0"] + w["x1"]) / 2 <= b for a, b in spans)
                              for w in figs)


MAX_HEAD_LINES = 3


def stacked_heads(blk, fs, i) -> list:
    """Indices of the heading lines stacked directly under heading line i
    (each header-like and closer to the one above than its own text
    size: less than a line of white): `Posted | Returned/` over `Date Posted | Fees`
    over `Amount | Items` is ONE heading three lines tall."""
    out, k = [], i
    while len(out) < MAX_HEAD_LINES - 1 and k + 1 < len(blk) and is_header_line(fs[k + 1]) \
            and blk[k + 1]["top"] - blk[k]["bottom"] < 1.0 * (blk[k].get("size") or 10):
        k += 1
        out.append(k)
    return out


def across(f, head_spans) -> bool:
    """A line with a figure that is no row of the table under it: one of its
    segments, holding no date and no amount, overlaps two or more of the
    heading's segments (`Count of items 8` laid across Ref | Day). A row's
    text sits under ONE heading."""
    # heading lines stacked over one column are ONE column: overlapping
    # spans merge
    spans = []
    for x0, x1 in sorted(head_spans):
        if spans and x0 < spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], x1)
        else:
            spans.append([x0, x1])
    head_spans = spans
    if len(head_spans) < 2:
        return False
    for sg in f["segs"]:
        if any(is_amount(w["text"]) or has_date(w["text"]) for w in sg):
            continue
        a, b = min(w["x0"] for w in sg), max(w["x1"] for w in sg)
        if sum(1 for x0, x1 in head_spans if a < x1 and x0 < b) >= 2:
            return True
    return False


def aligned_with(words, edges, tol=4.0) -> bool:
    """A `Label: figure` line whose figures end on the right edges of a
    table's figures above it is a row of that table (`Total Fees:`
    with its total under its column), not a free label/value pair."""
    nums = [w for w in words if is_numeric(w["text"])]
    return bool(nums) and bool(edges) and all(
        any(abs(w["x1"] - e) <= tol for e in edges) for w in nums)


# ── blocks and candidate rows ────────────────────────────────────────────────

def pitch(lines) -> float:
    gaps = [b["baseline"] - a["baseline"] for a, b in zip(lines, lines[1:])
            if b["baseline"] - a["baseline"] > 0.5]
    return statistics.median(gaps) if gaps else 12.0


def blocks(page) -> list:
    """Lines split where the vertical white space exceeds 1.6x the page's
    usual line pitch: [[line], ...] in page order."""
    lines = [ln for ln in page["lines"] if ln["word_ids"]]
    if not lines:
        return []
    p = pitch(lines)
    out, cur = [], [lines[0]]
    for a, b in zip(lines, lines[1:]):
        if b["top"] - a["bottom"] > 1.6 * p - (a["bottom"] - a["top"]):
            out.append(cur)
            cur = []
        cur.append(b)
    out.append(cur)
    return out


# ── side zones ───────────────────────────────────────────────────────────────

def side_split(page) -> Optional[float]:
    """The x of the alley separating a side panel, as perception found it
    (`perception.side_zone`): lines never cross it."""
    return page.get("side_split")


# ── table columns ────────────────────────────────────────────────────────────

def _coverage_alleys(lines_words, x_lo, x_hi, min_w=2.0) -> list:
    """x intervals inside [x_lo, x_hi] no word of any line covers."""
    spans = sorted((w["x0"], w["x1"]) for ws in lines_words for w in ws)
    alleys, cur = [], x_lo
    for a, b in spans:
        if a - cur >= min_w:
            alleys.append((cur, a))
        cur = max(cur, b)
    if x_hi - cur >= min_w:
        alleys.append((cur, x_hi))
    return alleys


def _right_edges(lines_words, tol=2.5) -> list:
    """x1 positions shared by numeric words of 2+ lines: right-aligned
    columns, as [(x1, count)]."""
    xs = sorted(w["x1"] for ws in lines_words for w in ws if is_numeric(w["text"]))
    groups = []
    for x in xs:
        if groups and x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return [(statistics.median(g), len(g)) for g in groups if len(g) >= 2]


def columns_for(data_words, header_words=(), gut: float = 8.0, wgap: float = 2.5) -> dict:
    """Candidate column boundaries and columns for a table.

    Columns are the x spans the DATA lines' ink covers, cut at alleys no
    data line crosses; a span holding two right-edge clusters of numeric
    words is cut between them (two right-aligned amount columns printed
    with ordinary spacing). Heading words do not make columns: a centred
    heading sits over its column, it does not define it."""
    allw = [w for ws in data_words for w in ws]
    if not allw:
        return {"boundaries": [], "columns": []}
    x_lo = min(w["x0"] for w in allw) - 1
    x_hi = max(w["x1"] for w in allw) + 1
    hw = [w for w in header_words or []]
    x_lo = min([x_lo] + [w["x0"] - 1 for w in hw])
    x_hi = max([x_hi] + [w["x1"] + 1 for w in hw])
    alleys = _coverage_alleys(data_words, x_lo, x_hi)
    # an alley is a column boundary when it is at least the page's gutter
    # wide, or - narrower, but wider than ordinary word spacing - when a
    # heading word starts just after it (`CHECK RUN | CHECK #` printed
    # with word spacing). Gaps between the words of a description are
    # neither, and never cut a column.
    # breaks in the heading's own ink (`Member` ... `Ref No`)
    head_breaks = [(x, y) for x, y in _coverage_alleys([hw], x_lo, x_hi, 2 * wgap)] if hw else []

    def real(a, b):
        if b - a >= gut:
            return True
        if b - a < 1.5 * wgap:
            return False
        # narrower than the gutter, but wider than word spacing: a boundary
        # when a heading word starts at it, or - at least half a gutter wide,
        # so the gap between two pieces of one word the text layer printed
        # apart (`ABC DEF`) never counts - when the heading itself breaks
        # over it (`Jane Roe 0001234` under `Member | Ref No`)
        return any(a - 2 <= w["x0"] <= b + 2 for w in hw) or (b - a >= 0.5 * gut and any(
            min(b, y) - max(a, x) > 0 for x, y in head_breaks))
    inner = [(a, b) for a, b in alleys if a > x_lo + 0.5 and b < x_hi - 0.5 and real(a, b)]
    bounds = [{"x": round((a + b) / 2, 1), "kind": "gap", "width": round(b - a, 1)}
              for a, b in inner]
    cuts = sorted(bd["x"] for bd in bounds)
    edges = [x_lo] + cuts + [x_hi]
    cols = [[edges[i], edges[i + 1]] for i in range(len(edges) - 1)]
    redges = _right_edges(data_words)
    out = []
    for c0, c1 in cols:
        inside = [x for x, n in redges if c0 < x <= c1]
        if len(inside) >= 2:
            # cut between consecutive right-edge clusters, at the widest gap
            # between the words ending at one and the words of the next
            inside.sort()
            pieces, start = [], c0
            for a, b in zip(inside, inside[1:]):
                lefts = [w["x0"] for w in allw if a < w["x1"] <= b + 2.5 and w["x0"] > a]
                cut = (a + min(lefts)) / 2 if lefts else (a + b) / 2
                if any(w["x0"] + 1 < cut < w["x1"] - 1 for w in allw):
                    # a data word's ink crosses it: two right edges a few
                    # points apart in ONE column (an OCR layer's jitter),
                    # not two columns
                    continue
                bounds.append({"x": round(cut, 1), "kind": "right_edge", "width": 0.0})
                pieces.append([start, cut])
                start = cut
            pieces.append([start, c1])
            out += pieces
        else:
            out.append([c0, c1])
    # a heading over NO data keeps its own column (an empty Credits column
    # is a column; its cells are blank, not merged into Debits)
    claims = []
    if hw:
        segs, cur = [], []
        for w in sorted(hw, key=lambda w: w["x0"]):
            if cur and w["x0"] - cur[-1]["x1"] > max(gut, 3 * wgap):
                segs.append(cur)
                cur = []
            cur.append(w)
        if cur:
            segs.append(cur)
        ink = []                             # each column's data ink span
        for c0, c1 in out:
            ws = [w for w in allw if c0 <= (w["x0"] + w["x1"]) / 2 <= c1]
            ink.append((min(w["x0"] for w in ws), max(w["x1"] for w in ws)) if ws else None)
        spans = [(min(w["x0"] for w in sg), max(w["x1"] for w in sg)) for sg in segs]
        headed = {i for i, sp in enumerate(ink) if sp and any(
            a < sp[1] + 2 and sp[0] - 2 < b for a, b in spans)}
        for sg in segs:
            a, b = min(w["x0"] for w in sg), max(w["x1"] for w in sg)
            if any(w["x0"] < b + 2 and a - 2 < w["x1"] for w in allw):
                continue                     # data is printed under it
            # a heading printed OFFSET from its column (centred over a wide
            # box, `Item Kind` far right of `Spare Parts`): it claims the
            # nearest data column that has no heading of its own, when no
            # headed column lies between them
            cand = []
            for i, sp in enumerate(ink):
                if not sp or i in headed:
                    continue
                lo_i, hi_i = sorted((i, next((k for k, c in enumerate(out)
                                              if c[0] <= (a + b) / 2 <= c[1]), i)))
                if any(k in headed for k in range(lo_i + 1, hi_i)):
                    continue
                cand.append((max(sp[0] - b, a - sp[1], 0.0), i))
            if cand:
                _d, i = min(cand)
                headed.add(i)
                claims.append({"col": i, "x0": a - 1, "x1": b + 1})
                continue
            # split the empty span it sits in around the heading
            for i, (c0, c1) in enumerate(out):
                if c0 <= (a + b) / 2 <= c1:
                    left = [w["x1"] for w in allw if c0 <= w["x1"] <= a]
                    right = [w["x0"] for w in allw if b <= w["x0"] <= c1]
                    lo = max(c0, (max(left) + a) / 2 if left else a - 1)
                    hi = min(c1, (b + min(right)) / 2 if right else b + 1)
                    pieces = [p for p in ([c0, lo], [lo, hi], [hi, c1])
                              if p[1] - p[0] > 0.5 and (p == [lo, hi] or any(
                                  p[0] <= (w["x0"] + w["x1"]) / 2 <= p[1] for w in allw))]
                    out[i:i + 1] = pieces
                    bounds += [{"x": round(lo, 1), "kind": "heading", "width": 0.0},
                               {"x": round(hi, 1), "kind": "heading", "width": 0.0}]
                    break
    result = []
    for ci, (c0, c1) in enumerate(out):
        ws = [w for w in allw if c0 <= (w["x0"] + w["x1"]) / 2 <= c1]
        # numeric by CELL, not by word: a description column whose entries
        # end in a number (`Item 4`) is text; a cell is numeric when every
        # word in it is
        cells_, cur = [], []
        for w in sorted(ws, key=lambda w: w.get("baseline", w["bottom"])):
            if cur and w.get("baseline", w["bottom"]) - cur[-1].get("baseline", cur[-1]["bottom"]) > 2.0:
                cells_.append(cur)
                cur = []
            cur.append(w)
        if cur:
            cells_.append(cur)
        nums = [max(cw, key=lambda w: w["x1"]) for cw in cells_
                if all(is_numeric(w["text"]) for w in cw)]
        numeric = bool(nums) and len(nums) * 2 >= len(cells_)
        right = numeric and (statistics.pstdev([w["x1"] for w in nums])
                             if len(nums) > 1 else 0) <= 3.0
        col = {"x0": round(c0, 1), "x1": round(c1, 1),
               "align": "right" if right else "left", "numeric": numeric}
        for cl in claims:
            # out[] may have been re-split after a claim was made: a claim
            # names the column holding the claimed data
            if cl["col"] == ci:
                col["heading_span"] = [round(cl["x0"], 1), round(cl["x1"], 1)]
        result.append(col)
    bounds.sort(key=lambda b: b["x"])
    return {"boundaries": bounds, "columns": result}


def column_of(word, cols) -> int:
    """The column a word belongs to: a right-aligned column takes a word
    whose RIGHT edge is within it (amounts line up on the right); otherwise
    the column the word's box overlaps most."""
    best, score = 0, -1e9
    for i, c in enumerate(cols):
        if c.get("align") == "right" and c["x0"] - 1 <= word["x1"] <= c["x1"] + 1:
            return i
        ov = min(word["x1"], c["x1"]) - max(word["x0"], c["x0"])
        if ov > score:
            best, score = i, ov
    return best


def header_labels(header_lines_words, cols) -> list:
    """Each column's heading, the words over it joined in reading order (a
    heading printed on two lines reads top then bottom)."""
    labels = [[] for _ in cols]
    if not cols:
        return []
    for ws in header_lines_words:
        for w in ws:
            cx = (w["x0"] + w["x1"]) / 2
            hit = next((i for i, c in enumerate(cols) if c.get("heading_span")
                        and c["heading_span"][0] <= cx <= c["heading_span"][1]), None)
            if hit is None:
                hit = column_of(dict(w, x1=w["x1"]), [dict(c, align="left") for c in cols])
            labels[hit].append(w["text"])
    return [" ".join(x) for x in labels]


def repeated_groups(labels) -> int:
    """k when the heading sequence is one group printed k times side by side
    (`Number Date Amount Number Date Amount` -> 2), else 1."""
    keys = [loose_key(x) for x in labels]
    n = len(keys)
    for size in range(1, n // 2 + 1):
        if n % size:
            continue
        k = n // size
        if k >= 2 and all(keys[i] == keys[i % size] for i in range(n)) and all(keys[:size]):
            return k
    return 1


# ── the fallback plan ────────────────────────────────────────────────────────

def _region(rid, kind, lines, **kw):
    return {"id": rid, "kind": kind, "line_ids": [ln["id"] for ln in lines], **kw}


def _group_header(f, words) -> bool:
    """An identifier then a name, no date, no amount: `7711 RIVER GOODS`."""
    if f["date"] or f["n_amounts"] or len(words) < 2:
        return False
    first = words[0]["text"]
    rest = " ".join(w["text"] for w in words[1:])
    return bool(re.fullmatch(r"[A-Za-z]{0,3}\d[\w-]*", first)) and not re.search(r"\d", rest)


def proposal(page) -> dict:
    """Candidate rows, blocks and per-block candidate columns, plus the
    fallback's region guess for each block. The structure a model is asked
    to CONFIRM."""
    gut = gutter(page)
    feats = {ln["id"]: features(page, ln, gut) for ln in page["lines"]}
    side = side_split(page)
    out = {"page": page["page"], "gutter": round(gut, 2), "side_split": side,
           "rows": [{"line_id": ln["id"], "top": ln["top"], "baseline": ln["baseline"]}
                    for ln in page["lines"]],
           "blocks": []}
    for bi, blk in enumerate(blocks(page)):
        fs = [feats[ln["id"]] for ln in blk]
        entry = {"id": f"b{bi + 1}", "line_ids": [ln["id"] for ln in blk],
                 "top": blk[0]["top"], "bottom": blk[-1]["bottom"]}
        heads = [i for i, f in enumerate(fs) if is_header_line(f)
                 and sum(1 for g in fs[i + 1:i + 6] if is_row_line(g)) >= 2]
        data = [ln for ln, f in zip(blk, fs) if is_row_line(f)]
        if heads or (len(data) >= 3 and sum(1 for f in fs if len(f["segs"]) >= 2) >= 3):
            h = heads[0] if heads else None
            body = blk[h + 1:] if h is not None else blk
            dws = [_words_of(page, ln) for ln in body if is_row_line(feats[ln["id"]])]
            hws = _words_of(page, blk[h]) if h is not None else []
            entry["columns"] = columns_for(dws, hws, gut, word_gap(page))
            entry["header_line_ids"] = [blk[h]["id"]] if h is not None else []
        out["blocks"].append(entry)
    return out


def fallback_plan(page, prev_table=None) -> dict:
    """A complete plan from geometry alone (3d). `prev_table` is the last
    table of the previous page, so a headless table continuing it keeps its
    columns and headings (headers printed only on page 1)."""
    gut = gutter(page)
    lines = page["lines"]
    feats = {ln["id"]: features(page, ln, gut) for ln in lines}
    body_sizes = [ln["size"] for ln in lines if ln.get("size")]
    body = statistics.median(body_sizes) if body_sizes else 10.0
    side = side_split(page)
    width = float(page.get("width") or 612)
    regions, ignored = [], []
    rid = 0

    def nid():
        nonlocal rid
        rid += 1
        return f"r{rid}"

    # a fillable form: widget values next to the labels of their boxes,
    # each form on the page its own region (form_boxes).
    # T3 S7: also try the flat-form path when STRUCTURE_READ_FLAT_FORMS is on.
    import form_boxes as FB
    try:
        from app.config import settings as _s
        _flat = bool(getattr(_s, "STRUCTURE_READ_FLAT_FORMS", False))
    except Exception:
        _flat = False
    taken = set()
    for fr in (FB.form_regions(page, flat_form=True)
               if _flat and not FB.has_widget_values(page)
               else FB.form_regions(page)):
        regions.append({"id": nid(), "kind": "form", "line_ids": fr["line_ids"],
                        "fields": fr["fields"]})
        taken.update(fr["line_ids"])
    lines = [ln for ln in lines if ln["id"] not in taken]
    in_side = set()
    if side is not None:
        narrow_right = (width - side) < 0.35 * width
        for ln in lines:
            on_side = ln["x0"] >= side if narrow_right else ln["x1"] <= side
            if on_side:
                in_side.add(ln["id"])
    side_lines = [ln for ln in lines if ln["id"] in in_side]
    if side_lines:
        regions.append(_region(nid(), "side", side_lines))
    main = [ln for ln in lines if ln["id"] not in in_side]
    sub = dict(page, lines=main)
    first_block = True
    for blk in blocks(sub):
        fs = [feats[ln["id"]] for ln in blk]
        i = 0
        # title: the page's first block, one line, large
        if first_block and len(blk) >= 1 and blk[0].get("size", 0) >= 1.3 * body \
                and len(fs[0]["segs"]) == 1 and not fs[0]["n_amounts"]:
            regions.append(_region(nid(), "title", [blk[0]]))
            i = 1
        first_block = False
        pending = []          # free lines waiting to become a kv region

        def flush():
            if pending:
                regions.append(_region(nid(), "kv", list(pending)))
                pending.clear()

        while i < len(blk):
            ln, f = blk[i], fs[i]
            if f["furniture"]:
                flush()
                ignored.append({"line_id": ln["id"], "reason": "page furniture"})
                i += 1
                continue
            if f["markup"]:
                flush()
                ignored.append({"line_id": ln["id"], "reason": MARKUP})
                i += 1
                continue
            pj = paragraph_run(blk, fs, i)
            if pj > i:
                flush()
                kind = "bullet text" if _BULLET.match(fs[i]["seg_texts"][0]) else \
                    "paragraph (instruction or explanation text)"
                regions.append(_region(nid(), "note", blk[i:pj], reason=kind))
                i = pj
                continue
            if f["prose"]:
                flush()
                j = i
                while j < len(blk) and (fs[j]["prose"] or (
                        j > i and not fs[j]["digits"] and not fs[j]["pair"]
                        and not fs[j]["widget"] and len(fs[j]["segs"]) == 1)):
                    j += 1
                regions.append(_region(nid(), "note", blk[i:j]))
                i = j
                continue
            starts = starts_table(sub, blk, fs, i, gut)
            headless = (prev_table is not None and not regions_has_table(regions)
                        and is_row_line(f) and len(f["segs"]) >= 2 and sum(
                            1 for g in fs[i:i + 4] if is_row_line(g)) >= 2)
            if starts or headless:
                flush()
                j = i + 1 if starts else i
                # stacked heading lines directly under the first
                head_ids = [ln["id"]] if starts else []
                if starts:
                    more = stacked_heads(blk, fs, i)
                    head_ids += [blk[m]["id"] for m in more]
                    j += len(more)
                k = j
                edges, skipped = [], []
                # the heading's own columns, to tell a row from a line laid
                # across the table
                hcent = [(min(w["x0"] for w in sg), max(w["x1"] for w in sg))
                         for h in head_ids for sg in segments(sub, next(
                             x for x in blk if x["id"] == h), gut)]
                while k < len(blk):
                    g = fs[k]
                    if g["prose"] or g["furniture"]:
                        break
                    if g["markup"]:
                        skipped.append(blk[k]["id"])
                        k += 1
                        continue
                    if k > j and starts_table(sub, blk, fs, k, gut):
                        break                      # the next table's heading
                    nxt = next((m for m in range(k + 1, min(k + 3, len(blk)))
                                if not fs[m]["markup"]), None)
                    close = k > j and blk[k]["baseline"] - blk[k - 1]["baseline"] <= \
                        1.5 * (blk[k].get("size") or body)
                    if k > j and not is_row_line(g) and not close and nxt is not None \
                            and starts_table(sub, blk, fs, nxt, gut):
                        break                      # the next table's title
                    if k > j and is_row_line(g) and across(g, hcent):
                        break                      # a summary laid across the table
                    if k > j and not is_row_line(g) and not close and                             (nxt is None or not is_row_line(fs[nxt]) or across(fs[nxt], hcent)):
                        break                      # a footnote after the rows
                    ws_k = _words_of(page, blk[k])
                    if g["pair"] and not is_row_line(g) and not aligned_with(ws_k, edges):
                        break
                    edges += [w["x1"] for w in ws_k if is_numeric(w["text"])]
                    k += 1
                ignored += [{"line_id": lid, "reason": MARKUP} for lid in skipped]
                keep = [x for x in blk[i:k] if x["id"] not in skipped]
                tlines = [x for x in blk[j:k] if x["id"] not in skipped]
                regions.append(_table_region(nid(), page, keep, head_ids, tlines,
                                             feats, prev_table if headless else None))
                prev_table = regions[-1]
                i = k
                continue
            if f["continued"] and not f["n_amounts"]:
                flush()
                ignored.append({"line_id": ln["id"], "reason": "continued marker"})
                i += 1
                continue
            pending.append(ln)
            i += 1
        flush()
    return {"version": 1, "page": page["page"], "source": "fallback",
            "regions": regions, "ignored": ignored, "contradictions": []}


_BULLET = re.compile(r"^\s*(?:[\u2022\u25aa\u25cf\u25e6\u2023\u2043*]|\(?\d{1,2}[.)])\s+\S")


def _plain(f) -> bool:
    """A line of running text: one segment, no date, no amount, no label
    pair, no widget, and at least half its words (after a bullet or list
    marker) starting lowercase - the shape of a sentence. A capitalised
    line item (`(5) ROTARY PUMP SPEC 20240G`) or a row of form box labels
    (`15 State Employer ID no. 16 State wages`) is not running text."""
    if not (len(f["segs"]) == 1 and not f["date"] and not f["n_amounts"] and not f["pair"]
            and not f["widget"]):
        return False
    toks = f["seg_texts"][0].split()
    if toks and _BULLET.match(f["seg_texts"][0]):
        toks = toks[1:]
    words = [t for t in toks if t[:1].isalpha()]
    return bool(words) and sum(1 for t in words if t[0].islower()) * 2 >= len(toks)


def paragraph_run(blk, fs, i) -> int:
    """End index of a paragraph or bullet item starting at line i, or i.

    A paragraph: two or more plain lines, starting at one left edge (the
    first may be indented), set one line under another, 8+ words in all,
    ending a sentence. A bullet item: a plain line opening with a bullet
    or `1.` / `(2)`, 4+ words, with its plain continuation lines. Text
    carrying a date or an amount is never here: a figure in a sentence may
    belong to a table, and a lost figure is invisible."""
    if not _plain(fs[i]):
        return i
    bullet = bool(_BULLET.match(fs[i]["seg_texts"][0]))
    j, x0 = i + 1, None
    while j < len(blk) and _plain(fs[j]) and not _BULLET.match(fs[j]["seg_texts"][0]):
        size = blk[j].get("size") or 10
        if blk[j]["baseline"] - blk[j - 1]["baseline"] > 1.8 * size:
            break
        x0 = blk[j]["x0"] if x0 is None else x0
        if abs(blk[j]["x0"] - x0) > 4.0:
            break
        j += 1
    words = sum(fs[k]["nwords"] for k in range(i, j))
    text = " ".join(blk[k]["text"] for k in range(i, j)).rstrip()
    if bullet and words >= 4:
        return j
    if j - i >= 2 and words >= 8 and text.endswith((".", "?", "!")) and \
            sum(1 for ch in text if ch.islower()) > sum(1 for ch in text if ch.isupper()):
        return j
    return i


def regions_has_table(regions) -> bool:
    return any(r["kind"] == "table" for r in regions)


def _table_region(rid, page, all_lines, head_ids, data_lines, feats, prev=None):
    by = {ln["id"]: ln for ln in page["lines"]}
    heads = [by[i] for i in head_ids]
    # a `Label: value` line inside a table (a group's `Date: ...` line) is no
    # row of its columns: it never cuts or shapes them
    row_lines = [ln for ln in data_lines if is_row_line(feats[ln["id"]])
                 and not feats[ln["id"]]["pair"]] or         [ln for ln in data_lines if is_row_line(feats[ln["id"]])]
    dws = [_words_of(page, ln) for ln in row_lines]
    hws = [w for h in heads for w in _words_of(page, h)]
    geo = columns_for(dws, hws, gutter(page), word_gap(page))
    cols = geo["columns"]
    if not cols and heads:
        # no row line gave a column (the rows carry no date/amount the
        # detector counts): the heading's own segments are the columns
        segs = segments(page, heads[0])
        cols = [{"x0": round(min(w["x0"] for w in sg) - 1, 1),
                 "x1": round(max(w["x1"] for w in sg) + 1, 1),
                 "align": "left", "numeric": False} for sg in segs]
        for a, b in zip(cols, cols[1:]):
            mid = round((a["x1"] + b["x0"]) / 2, 1)
            a["x1"], b["x0"] = mid, mid
    spans = []
    if prev is not None and not heads:
        # headers printed only on an earlier page: its headings, and its
        # columns placed where THIS page prints them. When this page shows
        # as many columns as the earlier table they correspond in order
        # (a page whose columns are shifted); otherwise the earlier columns
        # are moved by the shift of the first column's left edge.
        pcols = [dict(c) for c in prev["columns"]]
        labels = list(prev.get("labels") or [""] * len(pcols))
        if len(cols) == len(pcols):
            cols = [dict(c, align=p.get("align", c.get("align"))) for c, p in zip(cols, pcols)]
        else:
            first = min((w["x0"] for ws in dws for w in ws), default=pcols[0]["x0"])
            pfirst = pcols[0]["x0"]
            shift = first - pfirst - 1 if pcols else 0.0
            cols = [dict(c, x0=c["x0"] + shift, x1=c["x1"] + shift) for c in pcols]
        cont = True
    else:
        spans, span_ids = spanning_heads(page, heads, cols, dws)
        hwords = [[w for w in _words_of(page, h) if w["id"] not in span_ids] for h in heads]
        labels = header_labels(hwords[:1], cols)
        for hw_ in hwords[1:]:
            sub = header_labels([hw_], cols)
            labels = [a if not b else (f"{a} {b}".strip()) for a, b in zip(labels, sub)]
        cont = False
    groups = repeated_groups(labels) if labels else 1
    group_ids = [ln["id"] for ln in data_lines
                 if _group_header(feats[ln["id"]], _words_of(page, ln))]
    out = {"id": rid, "kind": "table",
           "line_ids": [ln["id"] for ln in all_lines],
           "header_line_ids": head_ids,
            "columns": cols, "labels": labels, "boundaries": geo["boundaries"],
           "column_groups": groups, "stacked_header": len(heads) > 1,
           "group_header_line_ids": group_ids, "continued": cont}
    if not cont and spans:
        out["spanning_heads"] = spans
    return out


def spanning_heads(page, heads, cols, data_words=()):
    """([{"text", "word_ids", "cols": [first, last]}], word ids) for heading
    segments that sit over TWO OR MORE of the bottom heading line's headings
    (`Refunds` over `Items | Amount`, `Total Gross Sales` over `Items |
    Amount`): a group heading, written as its own header row over the
    columns it spans - never cut into pieces and glued to each column's
    label. It must reach over 2+ bottom headings AND have a word over none
    of them; a run of headings each over its own bottom heading
    (`Employee Employee Employer` over `Current YTD Current`) is per-column."""
    out, ids = [], set()
    if len(heads) < 2 or len(cols) < 3:
        return out, ids
    g = gutter(page) / 2
    bottom = [(min(w["x0"] for w in sg), max(w["x1"] for w in sg))
              for sg in segments(page, heads[-1])]
    for h in heads[:-1]:
        for sg in segments(page, h):
            a, b = min(w["x0"] for w in sg), max(w["x1"] for w in sg)
            under = [k for k, (x0, x1) in enumerate(bottom) if x0 < b + g and a - g < x1]
            loose = any(not any(x0 - 1 <= (w["x0"] + w["x1"]) / 2 <= x1 + 1 for x0, x1 in bottom)
                        for w in sg)
            if len(under) < 2 or not loose or len(sg) > 6:
                continue
            lo, hi = bottom[under[0]][0], bottom[under[-1]][1]
            span = [i for i, c in enumerate(cols) if c["x0"] < hi and lo < c["x1"]]
            if len(span) >= 2:
                out.append({"text": " ".join(w["text"] for w in sg),
                            "word_ids": [w["id"] for w in sg], "cols": [span[0], span[-1]]})
                ids.update(w["id"] for w in sg)
    if len(out) and len(ids) >= sum(len(_words_of(page, h)) for h in heads):
        return [], set()                 # every heading would be a group: none is
    return out, ids
