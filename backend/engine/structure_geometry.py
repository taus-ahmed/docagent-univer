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
_CONT = re.compile(r"\(?\bcontinued\b\)?\s*$|\bcont'?d\b", re.I)


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
    prose = (nwords >= 8 and text.rstrip().endswith((".", "?", "!"))) or nwords >= 12
    seg_texts = [" ".join(w["text"] for w in s) for s in segs]
    pair = any(re.search(r"\S:(\s|$)", t) for t in seg_texts)
    return {"segs": segs, "seg_texts": seg_texts, "n_amounts": len(amounts),
            "date": has_date(text), "digits": bool(re.search(r"\d", text)),
            "prose": prose and not amounts, "pair": pair,
            "furniture": bool(_PAGE_NO.match(text)), "continued": bool(_CONT.search(text)),
            "nwords": nwords}


def is_header_line(f) -> bool:
    return len(f["segs"]) >= 2 and not f["digits"] and not f["pair"] and not f["prose"]


def is_row_line(f) -> bool:
    return f["date"] or f["n_amounts"] >= 1


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
    def real(a, b):
        if b - a >= gut:
            return True
        return b - a >= 1.5 * wgap and any(a - 2 <= w["x0"] <= b + 2 for w in hw)
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
                bounds.append({"x": round(cut, 1), "kind": "right_edge", "width": 0.0})
                pieces.append([start, cut])
                start = cut
            pieces.append([start, c1])
            out += pieces
        else:
            out.append([c0, c1])
    # a heading over NO data keeps its own column (an empty Credits column
    # is a column; its cells are blank, not merged into Debits)
    if hw:
        segs, cur = [], []
        for w in sorted(hw, key=lambda w: w["x0"]):
            if cur and w["x0"] - cur[-1]["x1"] > max(gut, 3 * wgap):
                segs.append(cur)
                cur = []
            cur.append(w)
        if cur:
            segs.append(cur)
        for sg in segs:
            a, b = min(w["x0"] for w in sg), max(w["x1"] for w in sg)
            if any(w["x0"] < b + 2 and a - 2 < w["x1"] for w in allw):
                continue                     # data is printed under it
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
    for c0, c1 in out:
        ws = [w for w in allw if c0 <= (w["x0"] + w["x1"]) / 2 <= c1]
        num = [w for w in ws if is_numeric(w["text"])]
        right = bool(num) and len(num) * 2 >= len(ws) and (
            statistics.pstdev([w["x1"] for w in num]) if len(num) > 1 else 0) <= 3.0
        result.append({"x0": round(c0, 1), "x1": round(c1, 1),
                       "align": "right" if right else "left",
                       "numeric": bool(num) and len(num) * 2 >= len(ws)})
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
    for ws in header_lines_words:
        for w in ws:
            labels[column_of(dict(w, x1=w["x1"]), [dict(c, align="left") for c in cols])
                   ].append(w["text"])
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
            if f["prose"]:
                flush()
                j = i
                while j < len(blk) and (fs[j]["prose"] or (
                        j > i and not fs[j]["digits"] and not fs[j]["pair"]
                        and len(fs[j]["segs"]) == 1)):
                    j += 1
                regions.append(_region(nid(), "note", blk[i:j]))
                i = j
                continue
            starts_table = is_header_line(f) and sum(
                1 for g in fs[i + 1:i + 6] if is_row_line(g)) >= 2
            headless = (prev_table is not None and not regions_has_table(regions)
                        and is_row_line(f) and len(f["segs"]) >= 2 and sum(
                            1 for g in fs[i:i + 4] if is_row_line(g)) >= 2)
            if starts_table or headless:
                flush()
                j = i + 1 if starts_table else i
                # stacked second heading line directly under the first
                head_ids = [ln["id"]] if starts_table else []
                if starts_table and j < len(blk) and is_header_line(fs[j]) \
                        and blk[j]["top"] - ln["bottom"] < 0.6 * (ln.get("size") or body):
                    head_ids.append(blk[j]["id"])
                    j += 1
                k = j
                while k < len(blk) and not fs[k]["prose"] and not fs[k]["furniture"] \
                        and not (fs[k]["pair"] and not is_row_line(fs[k])):
                    k += 1
                tlines = blk[j:k]
                regions.append(_table_region(nid(), page, blk[i:k], head_ids, tlines,
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


def regions_has_table(regions) -> bool:
    return any(r["kind"] == "table" for r in regions)


def _table_region(rid, page, all_lines, head_ids, data_lines, feats, prev=None):
    by = {ln["id"]: ln for ln in page["lines"]}
    heads = [by[i] for i in head_ids]
    row_lines = [ln for ln in data_lines if is_row_line(feats[ln["id"]])]
    dws = [_words_of(page, ln) for ln in row_lines]
    hws = [w for h in heads for w in _words_of(page, h)]
    geo = columns_for(dws, hws, gutter(page), word_gap(page))
    cols = geo["columns"]
    if prev is not None and not heads:
        # headers printed only on an earlier page: take its columns and
        # headings; this page's words go to them by right edge / overlap
        cols = [dict(c) for c in prev["columns"]]
        labels = list(prev.get("labels") or [""] * len(cols))
        cont = True
    else:
        labels = header_labels([_words_of(page, h) for h in heads[:1]], cols)
        if len(heads) > 1:
            sub = header_labels([_words_of(page, heads[1])], cols)
            labels = [a if not b else (f"{a} {b}".strip()) for a, b in zip(labels, sub)]
        cont = False
    groups = repeated_groups(labels) if labels else 1
    group_ids = [ln["id"] for ln in data_lines
                 if _group_header(feats[ln["id"]], _words_of(page, ln))]
    return {"id": rid, "kind": "table",
            "line_ids": [ln["id"] for ln in all_lines],
            "header_line_ids": head_ids,
            "columns": cols, "labels": labels, "boundaries": geo["boundaries"],
            "column_groups": groups, "stacked_header": len(heads) > 1,
            "group_header_line_ids": group_ids, "continued": cont}
