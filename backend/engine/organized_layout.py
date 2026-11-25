"""Organized layout (Run R, Part 2, v1): a page's fields and tables laid out
on a sheet the way the page prints them. See docs/ORGANIZED_LAYOUT_SPEC.md.

    layout(pdf_path) -> {"pages": [[Cell, ...], ...], "skipped": [why, ...],
                         "text_layer": bool}

A Cell is a dict: row, col (0-based, per page), text, kind ("label", "value",
"header", "text", "title"), bold, italic, size (sheet points), align
("center" or None), and for a value its typed form: number / date / None.

Everything is decided from POSITIONS and the text layer's own fonts: no model,
no guessed table structure. Pure: reads the file, writes nothing.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime

_MONEY = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\)?$")
_INT = re.compile(r"^\d{1,9}$")
_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_JOIN_PT = 1.5          # words closer than this are one token (OCR shards)
_BLANK_PITCH = 1.6      # white space over 1.6x the usual leaves a blank row


# ── reading ─────────────────────────────────────────────────────────────────

def _rgb(color):
    if color is None:
        return None
    if isinstance(color, (int, float)):
        v = float(color)
        return (v, v, v)
    vals = [float(c) for c in color if isinstance(c, (int, float))]
    if len(vals) == 1:
        return (vals[0],) * 3
    if len(vals) == 3:
        return tuple(vals)
    if len(vals) == 4:
        c, m, y, k = vals
        return ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return None


def _saturated(color) -> bool:
    rgb = _rgb(color)
    return bool(rgb) and max(rgb) - min(rgb) >= 0.5


def _words(page):
    """Words with font, size and a markup bit (rule 10)."""
    chars = page.chars
    sat = [c for c in chars if _saturated(c.get("non_stroking_color"))]
    markup_on = bool(chars) and len(sat) < 0.4 * len(chars)
    out = []
    for w in page.extract_words(extra_attrs=["fontname", "size"], keep_blank_chars=False):
        w["text"] = w["text"].replace("�", "")
        if not w["text"].strip():
            continue                      # an unmapped glyph, nothing printed
        inside = [c for c in chars if w["x0"] - 0.5 <= c["x0"] and c["x1"] <= w["x1"] + 0.5
                  and abs(c["top"] - w["top"]) < 2]
        red = sum(1 for c in inside if _saturated(c.get("non_stroking_color")))
        fn = str(w.get("fontname") or "")
        out.append({"text": w["text"], "x0": float(w["x0"]), "x1": float(w["x1"]),
                    "top": float(w["top"]), "bottom": float(w["bottom"]),
                    "size": float(w.get("size") or 0),
                    "bold": "bold" in fn.lower() or "black" in fn.lower(),
                    "italic": "italic" in fn.lower() or "oblique" in fn.lower(),
                    "markup": markup_on and inside and red * 2 > len(inside)})
    return out


def _lines(words):
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    if not words:
        return []
    h = statistics.median(w["bottom"] - w["top"] for w in words) or 10.0
    lines, cur = [], [words[0]]
    for w in words[1:]:
        if w["top"] - cur[0]["top"] <= 0.5 * h:
            cur.append(w)
        else:
            lines.append(sorted(cur, key=lambda x: x["x0"]))
            cur = [w]
    lines.append(sorted(cur, key=lambda x: x["x0"]))
    return lines


def _segments(line, gutter):
    segs, cur = [], [line[0]]
    for w in line[1:]:
        if w["x0"] - cur[-1]["x1"] > gutter:
            segs.append(cur)
            cur = [w]
        else:
            cur.append(w)
    segs.append(cur)
    return segs


def _text(ws) -> str:
    out = ""
    for i, w in enumerate(ws):
        if i and w["x0"] - ws[i - 1]["x1"] >= _JOIN_PT:
            out += " "
        out += w["text"]
    return out


def _seg(ws, kind="text"):
    sizes = [w["size"] for w in ws]
    return {"words": ws, "text": _text(ws), "x0": ws[0]["x0"], "x1": ws[-1]["x1"],
            "top": min(w["top"] for w in ws), "size": statistics.median(sizes),
            "bold": sum(w["bold"] for w in ws) * 2 > len(ws),
            "italic": sum(w["italic"] for w in ws) * 2 > len(ws), "kind": kind}


def sheet_size(size, body) -> int:
    """The page's type size on the sheet: body text (within 35% of the most
    common size, which an OCR layer scatters) is 11; a heading is scaled up
    from it (clamped at 28); small print is 9."""
    r = size / body if body else 1.0
    if r >= 1.35:
        return max(12, min(28, round(11 * r)))
    if r <= 0.65:
        return 9
    return 11


def _prose(ws) -> bool:
    t = _text(ws).strip()
    n = len(t.split())
    return n >= 12 or (n >= 8 and t.endswith((".", "?")))


# ── values ──────────────────────────────────────────────────────────────────

def typed(text):
    """(value, number_format) for a cell: money and integers as numbers,
    dates as dates, everything else the text as printed."""
    t = str(text or "").strip()
    flat = t.replace(" ", "")
    m = _DATE.match(flat)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2))), "mm/dd/yyyy"
        except ValueError:
            return t, None
    if _MONEY.match(flat) and any(ch.isdigit() for ch in flat):
        neg = flat.startswith("(") or flat.startswith("-")
        num = float(re.sub(r"[^\d.]", "", flat))
        num = -num if neg else num
        if "$" in flat:
            return num, '"$"#,##0.00'
        if "." in flat or "," in flat:
            return num, "#,##0.00"
        if _INT.match(flat):
            return int(num), "#,##0"
    return t, None


def _is_figure(text) -> bool:
    flat = str(text or "").replace(" ", "")
    return bool(_DATE.match(flat) or (_MONEY.match(flat) and any(c.isdigit() for c in flat)))


# ── the page ────────────────────────────────────────────────────────────────

def _split_pairs(seg):
    """A segment carrying `Label: value` -> [label seg, value seg]."""
    ws = seg["words"]
    for i, w in enumerate(ws):
        if w["text"].endswith(":") and len(w["text"]) > 1:
            lab = _seg(ws[:i + 1], "label")
            lab["text"] = lab["text"][:-1].rstrip()
            out = [lab]
            if i + 1 < len(ws):
                out.append(_seg(ws[i + 1:], "value"))
            return out
    return [seg]


def _columns(xs, body):
    """Runs of left edges: cut where neighbours are more than max(25, 2.8 x the
    body size) apart. [(lo, hi)] in page order."""
    xs = sorted(xs)
    if not xs:
        return []
    cut = max(25.0, 2.8 * body)
    runs, lo, prev = [], xs[0], xs[0]
    for x in xs[1:]:
        if x - prev > cut:
            runs.append((lo, prev))
            lo = x
        prev = x
    runs.append((lo, prev))
    return runs


def _col_of(x, runs):
    for i, (lo, hi) in enumerate(runs):
        if lo - 0.5 <= x <= hi + 0.5:
            return i
    return min(range(len(runs)), key=lambda i: min(abs(x - runs[i][0]), abs(x - runs[i][1])))


def page_cells(page):
    """[Cell] for one pdfplumber page; [] when it has no usable text layer."""
    words = [w for w in _words(page) if not w["markup"]]
    if len(words) < 5:
        return [], "no text layer on this page"
    body = statistics.mode(round(w["size"], 1) for w in words) or 11.0
    lines = _lines(words)
    gaps = [b["x0"] - a["x1"] for ln in lines for a, b in zip(ln, ln[1:]) if b["x0"] > a["x1"]]
    gutter = max(6.0, 4 * statistics.median(gaps)) if gaps else 12.0
    rows = []                                    # [(top, [seg])]
    for ln in lines:
        segs = []
        for s in _segments(ln, gutter):
            if _prose(s):
                continue
            segs.extend(_split_pairs(_seg(s)))
        if segs:
            rows.append((ln[0]["top"], segs))
    if not rows:
        return [], "only paragraph text on this page"
    # labels by position: a label's value is the next segment on its line
    for _top, segs in rows:
        for i, s in enumerate(segs):
            if s["kind"] == "label" and i + 1 < len(segs) and segs[i + 1]["kind"] == "text" \
                    and not segs[i + 1]["text"].endswith(":"):
                segs[i + 1]["kind"] = "value"
    # a centred title says nothing about where columns start
    runs = _columns([s["x0"] for k, (_t, segs) in enumerate(rows) for s in segs
                     if not (k == 0 and len(segs) == 1 and s["size"] >= 1.3 * body)], body)
    width = float(page.width)
    # the title: the first line, one segment, larger than the body, centred
    cells, out_row = [], 0
    # rule 3: spacing is the WHITE space between lines (a line's top less the
    # bottom of the line above it, wrapped lines included), against the
    # page's usual white space
    def _bottom(segs):
        return max(w["bottom"] for sg in segs for w in sg["words"])
    white = [b[0] - _bottom(a[1]) for a, b in zip(rows, rows[1:])]
    usual = statistics.median([w for w in white if w > 0] or [body * 0.5])
    prev_top, prev_bottom, prev_cells = None, None, []
    for k, (top, segs) in enumerate(rows):
        # continuation of the values directly above (rule 5)
        if prev_cells and prev_top is not None and top - prev_top <= 1.4 * max(
                s["size"] for s in segs) and all(s["kind"] == "text" for s in segs):
            above = {c["col"]: c for c in prev_cells if c["kind"] == "value"}
            cols = [_col_of(s["x0"], runs) for s in segs]
            if cols and all(c in above for c in cols):
                for s, c in zip(segs, cols):
                    above[c]["text"] += " " + s["text"]
                prev_top, prev_bottom = top, _bottom(segs)
                continue
        if prev_bottom is not None and top - prev_bottom > _BLANK_PITCH * usual:
            out_row += 1                          # one blank row, never more
        row_cells = []
        title = (k == 0 and len(segs) == 1 and segs[0]["size"] >= 1.3 * body)
        for s in segs:
            centre = (s["x0"] + s["x1"]) / 2
            centred_on_page = abs(centre - width / 2) <= 0.03 * width
            col = _col_of(centre if title and centred_on_page else s["x0"], runs)
            kind = "title" if title else s["kind"]
            row_cells.append({"row": out_row, "col": col, "text": s["text"], "kind": kind,
                              "bold": s["bold"], "italic": s["italic"],
                              "size": sheet_size(s["size"], body),
                              "align": "center" if title and centred_on_page else None})
        # one cell per column: a later segment in an occupied column joins it
        merged = {}
        for c in row_cells:
            if c["col"] in merged:
                merged[c["col"]]["text"] += " " + c["text"]
            else:
                merged[c["col"]] = c
        row_cells = list(merged.values())
        cells.extend(row_cells)
        prev_top, prev_bottom, prev_cells = top, _bottom(segs), row_cells
        out_row += 1
    # header rows (rule 6): label-free text cells, two or more, no figure,
    # directly above a row whose figures sit in the same columns
    by_row = {}
    for c in cells:
        by_row.setdefault(c["row"], []).append(c)
    for r, cs in by_row.items():
        nxt = by_row.get(r + 1) or []
        if len(cs) >= 2 and all(c["kind"] == "text" and not _is_figure(c["text"]) for c in cs):
            figs = {c["col"] for c in nxt if _is_figure(c["text"])}
            if figs and len(figs & {c["col"] for c in cs}) >= min(2, len(figs)):
                for c in cs:
                    c["kind"], c["bold"], c["align"] = "header", True, "center"
    for c in cells:
        if c["kind"] in ("value", "text"):
            c["value"], c["number_format"] = typed(c["text"])
        else:
            c["value"], c["number_format"] = c["text"], None
    return cells, None


def layout(pdf_path) -> dict:
    import pdfplumber
    pages, skipped = [], []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            cells, why = page_cells(page)
            if why:
                skipped.append(f"page {n}: {why}")
            if cells:
                pages.append(cells)
    return {"pages": pages, "skipped": skipped, "text_layer": bool(pages)}
