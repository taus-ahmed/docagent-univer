"""Run Q Phase 3 (Q7): check a table's rows against the page's GEOMETRY where
its text is drawn as outlines.

virtus_1099b prints its 1099-B records as vector outlines: the text layer
holds none of their values, and OCR reads them as noise ("SOOO of SSC.C000")
even at 600 dpi, so no span can be grounded. The stored model answer shifted
the withholding columns down a record, dropped a record, invented an
acquired date and ticked both check boxes on every record - and every one of
those passed as "could not be checked".

The page does carry, reliably:

  * the RECORDS - each a row of small check boxes, marked or not (an `X`
    character or a drawn mark inside the box);
  * WHERE it prints anything on each record - runs of outline glyphs or
    characters - which, gathered over the records, give the printed columns.

Printed columns and box columns are aligned to the template's columns by the
heading words above them, in left-to-right order (a monotonic alignment, so
one stray heading word cannot reorder them). A row is then compared with its
record, in order, only when the answer has exactly one row per record:

  * a value where the record prints nothing (invented, computed or another
    record's value);
  * an empty cell where the record prints something (a value in the wrong
    column);
  * a check box answered differently from the box drawn on the page.

No records, no boxes, or a row count that differs: no verdict at all.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_TRUE = {"x", "✓", "✔", "☒", "yes", "y", "true", "checked", "1", "on"}
_FALSE = {"", "no", "n", "false", "unchecked", "0", "off", "☐"}


def _glyphs(page):
    return [c for c in page.curves if 2 <= c["height"] <= 14 and c["width"] <= 14]


def outline_pages(file_path, min_glyphs=300, ratio=0.25):
    """File pages (1-based) drawing a substantial part of their text as
    outlines: at least `min_glyphs` glyph-sized paths and at least `ratio` of
    a path per text character. text_layer.outlined_pages (whole page drawn
    as outlines, ADP W-2 at 1.58) is the stricter case; virtus_1099b reads
    0.44, and every other page of the corpus under 0.07."""
    out = set()
    try:
        import pdfplumber
        with pdfplumber.open(str(file_path)) as pdf:
            for n, p in enumerate(pdf.pages, 1):
                g = len(_glyphs(p))
                if g >= min_glyphs and g >= ratio * max(1, len(p.chars)):
                    out.add(n)
    except Exception:
        return set()
    return out


def _inside(o, b, pad=1.0):
    return (o["x0"] >= b["x0"] - pad and o["x1"] <= b["x1"] + pad
            and o["top"] >= b["top"] - pad - 1 and o["bottom"] <= b["bottom"] + pad + 1)


def _cluster(values, tol):
    """Groups of sorted numbers no further than `tol` apart."""
    out = []
    for v in sorted(values):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return out


def _grid(page):
    boxes = [r for r in page.rects
             if 4 <= r["width"] <= 14 and abs(r["width"] - r["height"]) < 2
             and not r.get("fill")]
    if not boxes:
        return None
    marks = [c for c in page.chars if c["text"].strip()] + _glyphs(page) + list(page.lines)
    ys = _cluster([(b["top"] + b["bottom"]) / 2 for b in boxes], 2.5)
    rows = []
    for g in ys:
        lo, hi = g[0] - 0.01, g[-1] + 0.01
        rb = [b for b in boxes if lo <= (b["top"] + b["bottom"]) / 2 <= hi]
        if len(rb) >= 2:                       # a record carries several boxes
            rows.append(rb)
    if len(rows) < 2:
        return None
    xs = _cluster([(b["x0"] + b["x1"]) / 2 for rb in rows for b in rb], 3.0)
    cols = [sum(g) / len(g) for g in xs if len(g) >= 2]
    out_rows = []
    for rb in rows:
        marked = []
        for cx in cols:
            b = next((b for b in rb if abs((b["x0"] + b["x1"]) / 2 - cx) <= 3.0), None)
            if b is None:
                break
            marked.append(any(_inside(m, b) and m is not b for m in marks))
        if len(marked) == len(cols):
            out_rows.append({"y": sum((b["top"] + b["bottom"]) / 2 for b in rb) / len(rb),
                             "boxes": rb, "marked": marked})
    if len(out_rows) < 2 or not cols:
        return None
    return {"columns": cols, "rows": out_rows}


def box_grid(file_path, page_no):
    """{"columns": [box x-centre], "rows": [{"y", "marked": [bool]}]} for the
    records of check boxes on a page, or None."""
    import pdfplumber
    with pdfplumber.open(str(file_path)) as pdf:
        g = _grid(pdf.pages[page_no - 1])
    if g:
        for r in g["rows"]:
            r.pop("boxes", None)
    return g


def _runs(page, grid, row):
    """The x-spans the page prints on one record, boxes left out."""
    y = row["y"]
    boxes = [b for r in grid["rows"] for b in r["boxes"]]
    ink = [o for o in _glyphs(page) + [c for c in page.chars if c["text"].strip()]
           if abs((o["top"] + o["bottom"]) / 2 - y) <= 3.5
           and not any(_inside(o, b) for b in boxes)]
    runs = []
    for o in sorted(ink, key=lambda o: o["x0"]):
        if runs and o["x0"] - runs[-1][1] <= 4.0:
            runs[-1][1] = max(runs[-1][1], o["x1"])
        else:
            runs.append([o["x0"], o["x1"]])
    return runs


def _tokens(s):
    return set(re.findall(r"[a-z0-9]+", str(s).casefold()))


def _heading_centres(page, keys, top):
    """{key: x-centre of the heading words naming it} from the words in the
    band of lines just above the first record."""
    words = [w for w in page.extract_words() if top - 45 <= w["top"] <= top - 2]
    out = {}
    for k in keys:
        kt = _tokens(k)
        xs = sorted((w["x0"] + w["x1"]) / 2 for w in words if _tokens(w["text"]) & kt)
        out[k] = xs[len(xs) // 2] if xs else None
    return out


def _align(items, cols):
    """Monotonic assignment of `items` (sorted x-centres) to `cols` (template
    order, x-centre or None), each item to a distinct column, least total
    distance. Returns [column index per item] or None."""
    n, m = len(items), len(cols)
    if n > m:
        return None
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        cost[0][j] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            skip = cost[i][j - 1]
            c = cols[j - 1]
            d = 40.0 if c is None else abs(items[i - 1] - c)
            take = cost[i - 1][j - 1] + d
            if take <= skip:
                cost[i][j], back[i][j] = take, "take"
            else:
                cost[i][j], back[i][j] = skip, "skip"
    if cost[n][m] == INF:
        return None
    out, i, j = [None] * n, n, m
    while i > 0:
        if back[i][j] == "take":
            out[i - 1] = j - 1
            i -= 1
        j -= 1
    return out


def _num(v):
    s = str(v or "").replace(",", "").replace("$", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return Decimal(s) if re.fullmatch(r"-?\d+(?:\.\d+)?", s) else None
    except InvalidOperation:
        return None


def computed_from(row, col):
    """'A - B' (or +, x) when the row's `col` value equals that arithmetic of
    two other numbers in the row; else None."""
    target = _num(row.get(col))
    if target is None:
        return None
    nums = [(str(v).strip(), _num(v)) for k, v in row.items()
            if k != col and not str(k).startswith("_") and _num(v) is not None]
    for i, (sa, a) in enumerate(nums):
        for sb, b in nums[i + 1:]:
            for expr, val in ((f"{sa} - {sb}", a - b), (f"{sb} - {sa}", b - a),
                              (f"{sa} + {sb}", a + b), (f"{sa} x {sb}", a * b)):
                if val == target:
                    return expr
    return None


def check_rows(file_path, page_no, keys, rows):
    """[[(key, reason)] per row] comparing each answered row with the printed
    record in the same position, or None (no verdict)."""
    try:
        import pdfplumber
        with pdfplumber.open(str(file_path)) as pdf:
            page = pdf.pages[page_no - 1]
            grid = _grid(page)
            if not grid or len(grid["rows"]) != len(rows) or not rows:
                return None
            runs = [_runs(page, grid, r) for r in grid["rows"]]
            spans = []
            for x0, x1 in sorted(s for rr in runs for s in rr):
                if spans and x0 <= spans[-1][1]:
                    spans[-1][1] = max(spans[-1][1], x1)
                else:
                    spans.append([x0, x1])
            top = min(b["top"] for b in grid["rows"][0]["boxes"])
            heads = _heading_centres(page, keys, top)
    except Exception:
        return None
    items = sorted([((a + b) / 2, "ink", i) for i, (a, b) in enumerate(spans)]
                   + [(x, "box", i) for i, x in enumerate(grid["columns"])])
    where = _align([c for c, _k, _i in items], [heads[k] for k in keys])
    if where is None:
        return None
    ink_col = {keys[where[n]]: idx for n, (_c, kind, idx) in enumerate(items) if kind == "ink"}
    box_col = {keys[where[n]]: idx for n, (_c, kind, idx) in enumerate(items) if kind == "box"}
    out = []
    for n, (row, rec) in enumerate(zip(rows, grid["rows"])):
        probs = []
        printed = {k: any(not (b < spans[i][0] or a > spans[i][1]) for a, b in runs[n])
                   for k, i in ink_col.items()}
        for k in keys:
            v = str(row.get(k, "") or "").strip()
            if k in box_col:
                want = rec["marked"][box_col[k]]
                said = v.casefold()
                if said in _TRUE and not want:
                    probs.append((k, f"the box under {k!r} is not checked on printed "
                                     f"record {n + 1}, but the answer marks it"))
                elif said in _FALSE and want:
                    probs.append((k, f"the box under {k!r} is checked on printed "
                                     f"record {n + 1}, but the answer leaves it empty"))
                continue
            has_ink = printed.get(k, False)
            if v and not has_ink:
                c = computed_from(row, k)
                probs.append((k, f"the page prints nothing under {k!r} on printed record "
                                 f"{n + 1}" + (f" - the value equals {c}, computed, not "
                                               f"printed" if c else
                                               " - invented, or another record's value")))
            elif not v and has_ink:
                probs.append((k, f"the page prints a value under {k!r} on printed record "
                                 f"{n + 1} that the answer leaves empty - a value may "
                                 f"be in the wrong column"))
        out.append(probs)
    return out
