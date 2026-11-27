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


_GLUED = re.compile(r"^([A-Za-z][a-z]+\.?)(\$?\d[\d,]*(?:\.\d{1,2})?)$")


def _unglue(w):
    """Run T, 10 - a word the text layer printed with no space between a
    word and a figure ("Checks$1,783.32", "of6"): two words, the split
    placed by character share. An identifier ("INV2024", "ID7") has no
    lowercase run and is left whole."""
    m = _GLUED.match(w["text"])
    if not m:
        return [w]
    a, b = m.group(1), m.group(2)
    x = w["x0"] + (w["x1"] - w["x0"]) * len(a) / len(w["text"])
    return [dict(w, text=a, x1=x - 1.0), dict(w, text=b, x0=x + 1.0)]


def _words(page):
    """Words with font, size and a markup bit (rule 10). Cached on the page:
    `layout` reads every page twice (columns, then cells)."""
    got = getattr(page, "_organized_words", None)
    if got is not None:
        return [dict(w) for w in got]
    out = _read_words(page)
    try:
        page._organized_words = out
    except Exception:
        pass
    return [dict(w) for w in out]


def _read_words(page):
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
        out.extend(_unglue({"text": w["text"], "x0": float(w["x0"]), "x1": float(w["x1"]),
                            "top": float(w["top"]), "bottom": float(w["bottom"]),
                            "size": float(w.get("size") or 0),
                            "bold": "bold" in fn.lower() or "black" in fn.lower(),
                            "italic": "italic" in fn.lower() or "oblique" in fn.lower(),
                            "markup": bool(markup_on and inside and red * 2 > len(inside))}))
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


def page_gutter(lines, body):
    """The gap that separates two cells on this page: 4x the ordinary gap
    between two words of a phrase. Measured on the SMALL gaps only (under
    0.6 em): on a page of one-word cells most gaps ARE column gaps, and their
    median made the gutter swallow the columns (Run S, Stage 2)."""
    gaps = [b["x0"] - a["x1"] for ln in lines for a, b in zip(ln, ln[1:])
            if b["x0"] > a["x1"]]
    small = [g for g in gaps if g < 0.6 * (body or 11.0)]
    if small:
        return max(6.0, 4 * statistics.median(small))
    return max(6.0, 1.2 * (body or 11.0))


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
    # a line carrying two or more figures is a row of a table or a form,
    # however many words it has (rule 17: nothing printed is left out)
    figs = sum(1 for w in t.split() if _is_figure(w))
    if figs >= 2:
        return False
    return n >= 12 or (n >= 8 and t.endswith((".", "?")))


def _rules(page):
    """Horizontal strokes of the page: [(x0, x1, y, thickness)] in page
    coordinates (y from the top), from line objects and thin rectangles."""
    out = []
    for ln in getattr(page, "lines", None) or []:
        try:
            if abs(float(ln["top"]) - float(ln["bottom"])) <= 1.0:
                out.append((float(ln["x0"]), float(ln["x1"]), float(ln["top"]),
                            float(ln.get("linewidth") or 1.0)))
        except (KeyError, TypeError, ValueError):
            continue
    for r in getattr(page, "rects", None) or []:
        try:
            h = float(r["bottom"]) - float(r["top"])
            if 0 < h <= 6.0 and float(r["x1"]) - float(r["x0"]) > 4 * h:
                out.append((float(r["x0"]), float(r["x1"]), float(r["top"]), h))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _underlined(seg, rules) -> bool:
    """Rule 13: a stroke at most 1.5 pt thick within 3 pt under the segment,
    covering 80% of its width and not much wider than it."""
    w = seg["x1"] - seg["x0"]
    bottom = max(x["bottom"] for x in seg["words"])
    for x0, x1, y, th in rules:
        if th > 1.5 or not (bottom - 1.0 <= y <= bottom + 3.0):
            continue
        cover = min(x1, seg["x1"]) - max(x0, seg["x0"])
        if w > 0 and cover >= 0.8 * w and (x1 - x0) <= 1.5 * w + 10:
            return True
    return False


def _thick(rules, width):
    """Rule 14: the y of every thick rule (1.5 pt or more, 30% of the page)."""
    return sorted(y for x0, x1, y, th in rules if th >= 1.5 and (x1 - x0) >= 0.3 * width)


# ── values ──────────────────────────────────────────────────────────────────

DATE_FORMAT = "mm/dd/yyyy"        # rule 16: ONE date format on the sheet


def _as_date(text, order=None):
    """A real date for any printed notation, or None. Day/month order from
    `order` (the document's own); an order nothing settles is not guessed."""
    import dates as D
    t = str(text or "").strip()
    if not t or not re.search(r"\d", t) or len(t) > 24:
        return None
    d = D.parse_date(t, order)
    if not d.ok:
        return None
    return datetime(d.value.year, d.value.month, d.value.day)


def _identifier_label(label) -> bool:
    try:
        from app.services.excel_cells import labels_an_identifier
    except Exception:                                  # engine used on its own
        return bool(re.search(r"\b(id|no|number|invoice|check|po|zip|account)\b|#|p\.o",
                              str(label or ""), re.I))
    return labels_an_identifier(label)


def typed(text, order=None, label=None):
    """(value, number_format) for a cell: money and integers as numbers,
    dates as dates (one format, rule 16), everything else the text as
    printed.

    Run T, 7/8 - the page's notation is kept. A TRAILING minus ("26.08-")
    is a negative number shown trailing (`#,##0.00;#,##0.00-`); a leading
    minus and parentheses show as printed. A digit run that is an IDENTIFIER
    - zero-padded ("0025"), 9+ digits, or under a heading naming one
    (`label`: INVOICE, P.O., CHECK #, ZIP) - is text, every printed
    character kept. Money keeps the decimals it printed (75.00, not 75)."""
    t = str(text or "").strip()
    flat = t.replace(" ", "")
    d = _as_date(t, order)
    if d is not None:
        return d, DATE_FORMAT
    if re.fullmatch(r"\d+", flat) and (
            (flat[0] == "0" and len(flat) > 1) or len(flat) >= 9
            or (label and _identifier_label(label))):
        return t, None
    trailing = bool(re.fullmatch(r"\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?-", flat))
    body = flat[:-1] if trailing else flat
    if _MONEY.match(body) and any(ch.isdigit() for ch in body):
        neg = trailing or body.startswith("(") or body.startswith("-")
        num = float(re.sub(r"[^\d.]", "", body))
        num = -num if neg else num
        dec = len(body.rstrip(")").split(".")[1]) if "." in body else 0
        base = ("#,##0." + "0" * dec) if dec else "#,##0"
        if "$" in body:
            base = '"$"' + (base if dec else "#,##0.00")
        elif not ("." in body or "," in body):
            if not _INT.match(body.lstrip("-")):
                return t, None
            base = "#,##0"
            num = int(num)
        if trailing:
            return num, f"{base};{base}-"
        if body.startswith("("):
            return num, f"{base}_);({base})"
        return num, base
    return t, None


def _is_figure(text) -> bool:
    flat = str(text or "").replace(" ", "")
    return bool(_DATE.match(flat) or (_MONEY.match(flat) and any(c.isdigit() for c in flat))
                or _as_date(text, "MDY") is not None)


# ── the page ────────────────────────────────────────────────────────────────

def _split_pairs(seg):
    """A segment carrying `Label: value` pairs -> [label, value, label, value,
    ...] (Run T, 10: every pair, not only the first - "Account: XXXX-0000
    Period: 08/01/2026" is two pairs). The label of a later pair is the words
    after the previous value's last figure, or else the one word before its
    colon."""
    ws = seg["words"]
    if not any(w["text"].endswith(":") and len(w["text"]) > 1 for w in ws):
        return [seg]
    out, cur = [], []
    for w in ws:
        cur.append(w)
        if not (w["text"].endswith(":") and len(w["text"]) > 1):
            continue
        digit = [i for i, x in enumerate(cur[:-1]) if re.search(r"\d", x["text"])]
        if not out:
            j = 0                                  # the first label: all of it
        elif digit:
            j = max(digit[-1] + 1, len(cur) - 4)
        else:
            j = len(cur) - 1
        before, lab = cur[:j], cur[j:]
        if before:
            out.append(_seg(before, "value" if out and out[-1]["kind"] == "label" else "text"))
        lab_s = _seg(lab, "label")
        lab_s["text"] = lab_s["text"][:-1].rstrip()
        out.append(lab_s)
        cur = []
    if cur:
        out.append(_seg(cur, "value" if out and out[-1]["kind"] == "label" else "text"))
    return out


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


_PAGE_NO = re.compile(r"^\s*page\s+\d+(\s*(of|/)\s*\d+)?\s*$", re.I)

# ── page furniture (rule 12, Run T 10) ──────────────────────────────────────
#
# What a report or a form prints ABOUT itself, never part of its content: when
# and by whom it was run, the program that ran it, page numbers, and the
# instructions printed on a form. Shapes, not documents: every pattern names a
# kind of line any report or form may carry.
_FURNITURE = [
    re.compile(r"^\s*(report\s+)?(generated|printed|run|created|produced)(\s+(on|at|by|date|time))?\s*:?\s*\d", re.I),
    re.compile(r"^\s*(report|run|print)\s+(date|time)\s*:?\s*\d", re.I),
    re.compile(r"^\s*(user|user\s*id|operator|program(\s+(id|name|no\.?))?|report\s*(id|no\.?)|job\s*(id|no\.?))\s*[:#]", re.I),
    re.compile(r"^\s*page\s*:?\s*\d+(\s*(of|/)\s*\d+)?\s*$", re.I),
    re.compile(r"\b(see (the )?(separate |back for )?instructions|instructions for (recipient|form|filer)|"
               r"for privacy act|paperwork reduction act|keep (this|for your) (copy|records)|"
               r"do not (cut|staple|separate|write)|this information is being furnished|"
               r"cat\.\s*no\.|omb no\.)", re.I),
]


def _furniture(text) -> bool:
    return any(p.search(str(text or "")) for p in _FURNITURE)


def _row_key(segs):
    """A line's identity for rule 11: its text, with a "(continued)" mark
    dropped, so a section heading reprinted on the next page as "(continued)"
    is the same heading - one heading per section."""
    return tuple(re.sub(r"\s+", " ", re.sub(r"\(?\bcontinued\b\)?", "", s["text"], flags=re.I))
                 .strip().casefold() for s in segs)


# ── tables (Run T 2/3/4/9/10) ────────────────────────────────────────────────
#
# A table's COLUMNS are the white alleys its data rows leave: every x covered
# by some data row's ink is inside a column, every x no data row touches is
# between two. That is read once per table from the rows themselves, so a
# row's words are split exactly where the page's columns are - "75.00
# 07/22/2026 INV PD" printed with ordinary word spacing is four cells, because
# four columns' alleys run through it. The heading line's words go to the
# column each sits over, so "CHECK RUN CHECK #" is two headings. Nothing about
# what a column holds is guessed.

_STRONG_DATE = re.compile(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$")
_STRONG_MONEY = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?-?$|^\(?-?\$\d")


def _strong(tok) -> bool:
    """A date or an amount of money: what makes a line a ROW of a table.
    A bare integer is not ("NBR 131" is a reference, not a row)."""
    t = str(tok or "").strip().strip(",;")
    return bool(_STRONG_DATE.match(t) or _STRONG_MONEY.match(t))


def _line_info(ln, segs):
    toks = [w["text"] for w in ln]
    return {"words": ln, "segs": segs, "top": ln[0]["top"],
            "bottom": max(w["bottom"] for w in ln), "x0": ln[0]["x0"],
            "strong": sum(1 for t in toks if _strong(t)),
            "figs": sum(1 for t in toks if _is_figure(t)),
            "label": any(s["kind"] == "label" for s in segs),
            "text": " ".join(toks)}


def _header_like(li) -> bool:
    """A table's heading line: two or more headings (segments), no figure,
    no label. A title is one segment and is never a heading line."""
    return (li["figs"] == 0 and not li["label"] and 2 <= len(li["words"]) <= 24
            and len(li["segs"]) >= 2
            and not li["text"].rstrip().endswith((".", ":")))


def _group_parts(li):
    """(ident, name) of a group line - an identifier and a name, no date or
    amount - or None."""
    if li["strong"] or li["label"]:
        return None
    from row_groups import split_group_label
    p = split_group_label(li["text"])
    if p.get("ident") and p.get("name") and re.search(r"\d", p["ident"]) \
            and re.search(r"[A-Za-z]{2}", p["name"]) and not p.get("label"):
        return p["ident"], p["name"]
    return None


def _alleys(lines, n_min=0):
    """Column intervals [(x0, x1)] from the ink of `lines`' words: maximal runs
    of x covered by more than `n_min` lines."""
    if not lines:
        return []
    lo = int(min(w["x0"] for li in lines for w in li["words"]))
    hi = int(max(w["x1"] for li in lines for w in li["words"])) + 2
    cover = [0] * (hi - lo + 2)
    for li in lines:
        hit = set()
        for w in li["words"]:
            hit.update(range(int(w["x0"]) - lo, int(w["x1"]) - lo + 1))
        for x in hit:
            cover[x] += 1
    cols, start = [], None
    for i, c in enumerate(cover):
        if c > n_min and start is None:
            start = i
        elif c <= n_min and start is not None:
            cols.append((float(start + lo), float(i - 1 + lo)))
            start = None
    return cols


def _col_for(w, cols, near=15.0):
    """Index of the column a word belongs to: most overlap, else the nearest
    within `near` pt, else None."""
    best, bo = None, 0.0
    for i, (a, b) in enumerate(cols):
        o = min(b, w["x1"]) - max(a, w["x0"])
        if o > bo:
            best, bo = i, o
    if best is not None:
        return best
    cands = [(min(abs(w["x0"] - b), abs(w["x1"] - a)), i) for i, (a, b) in enumerate(cols)]
    d, i = min(cands) if cands else (None, None)
    return i if d is not None and d <= near else None


def _period(names):
    """The repeat period of a heading sequence ([Number, Date, Amount] x 3 ->
    3), or None."""
    n = len(names)
    for p in range(2, n // 2 + 1):
        if n % p == 0 and all(names[i] and names[i] == names[i % p] for i in range(n)):
            return p
    return None


def _sort_key(text):
    import dates as D
    t = str(text or "").strip()
    if _STRONG_DATE.match(t):
        d = D.parse_date(t, "MDY")
        return (0, d.value.toordinal()) if d.ok else None
    digits = re.sub(r"[^\d.]", "", t)
    try:
        return (1, float(digits)) if digits and re.match(r"^\d", t) else None
    except ValueError:
        return None


def _find_tables(infos):
    """[(header index, [stacked header index], [(kind, line index)])] over the
    page's kept lines. kind: data, tail, group, label, repeat."""
    tables, i, n = [], 0, len(infos)
    while i < n:
        li = infos[i]
        if not _header_like(li):
            i += 1
            continue
        heads, j = [i], i + 1
        # a second heading line directly below, its words under the first's:
        # STACKED headings (Tran Date over Post Date)
        if j < n and infos[j]["figs"] == 0 and not infos[j]["label"] and \
                infos[j]["top"] - li["bottom"] <= 0.8 * (li["bottom"] - li["top"]) + 2:
            span = [(w["x0"] - 3, w["x1"] + 3) for w in li["words"]]
            under = sum(1 for w in infos[j]["words"]
                        if any(a <= (w["x0"] + w["x1"]) / 2 <= b for a, b in span))
            if under * 2 >= len(infos[j]["words"]):
                heads.append(j)
                j += 1
        # the first data row: directly below, or past one group line
        k = j
        while k < n and k <= j + 1 and _group_parts(infos[k]):
            k += 1
        if k >= n or infos[k]["strong"] == 0 or infos[k]["figs"] < 2 or infos[k]["label"]:
            i += 1
            continue
        hx0 = min(w["x0"] for h in heads for w in infos[h]["words"])
        hx1 = max(w["x1"] for h in heads for w in infos[h]["words"])
        if not (infos[k]["words"][0]["x0"] >= hx0 - 40 and infos[k]["words"][-1]["x1"] <= hx1 + 60):
            i += 1
            continue
        body, prev_data, m, pitch = [], None, j, None
        hkey = _row_key([{"text": infos[i]["text"]}])
        first_x1 = infos[i]["words"][0]["x1"]
        while m < n:
            b = infos[m]
            if _row_key([{"text": b["text"]}]) == hkey:
                body.append(("repeat", m))
                m += 1
                continue
            if b["label"]:
                # a line of `Label: value` pairs is never a row of the table
                # ("CHECK DATE: 06/24/2026" under a row stays a pair)
                body.append(("label", m))
                m += 1
                continue
            if b["strong"]:
                body.append(("data", m))
                if prev_data is not None:
                    g = b["top"] - infos[prev_data]["top"]
                    if g > 0:
                        pitch = g if pitch is None else min(pitch, g)
                prev_data = m
                m += 1
                continue
            if b["label"]:
                body.append(("label", m))
                m += 1
                continue
            # Run T, 2 - a line with no date and no amount directly under a
            # row (closer than rows are to each other), starting right of the
            # table's first column, CONTINUES that row ("NBR 131" under a
            # transaction): it is never a row of its own
            last = body[-1] if body else None
            if last and last[0] in ("data", "tail"):
                above = infos[last[1]]
                gap = b["top"] - above["top"]
                line_h = above["bottom"] - above["top"]
                if gap <= max(1.25 * line_h, 0.85 * (pitch or 1e9)) \
                        and b["words"][0]["x0"] > first_x1 + 2:
                    body.append(("tail", m))
                    m += 1
                    continue
            if _group_parts(b) and any(infos[q]["strong"] for q in range(m + 1, min(n, m + 3))):
                body.append(("group", m))
                m += 1
                continue
            break
        # what follows the last row belongs to the table only when it sits
        # as close as a row's own note does ("CHECK DATE:" under the last
        # invoice); a group line with no rows under it never does
        while body and body[-1][0] in ("label", "group", "repeat"):
            kind_, idx = body[-1]
            prev = infos[body[-2][1]] if len(body) >= 2 else infos[i]
            close = infos[idx]["top"] - prev["top"] <= 1.5 * (pitch or 2 * (prev["bottom"] - prev["top"]))
            if kind_ == "label" and close:
                break
            body.pop()
        if any(kind == "data" for kind, _ in body):
            tables.append((i, heads[1:], body))
            i = body[-1][1] + 1
        else:
            i += 1
    return tables


def _lines_text(ws) -> str:
    """Words of one cell, a line at a time: a continuation line is joined
    with a space ("...STORE" + "NBR 131"), never glued to the line above."""
    out, cur = [], []
    for w in ws:
        if cur and abs(w["top"] - cur[-1]["top"]) > 2.0:
            out.append(_text(cur))
            cur = []
        cur.append(w)
    if cur:
        out.append(_text(cur))
    return " ".join(out)


def _cell(row, key, ws, kind, label=None, text=None):
    return {"row": row, "key": key, "text": _lines_text(ws) if text is None else text,
            "kind": kind,
            "bold": sum(w["bold"] for w in ws) * 2 > len(ws),
            "italic": sum(w["italic"] for w in ws) * 2 > len(ws),
            "underline": False, "_size": statistics.median(w["size"] for w in ws),
            "align": None, "_bottom": max(w["bottom"] for w in ws), "_label": label}


def _emit_table(tbl, infos, run_of, trace, seen, gutter=6.0):
    """The cells of one table, keyed (page run, sub) so that columns closer
    than the page's column cut still get a sheet column each; group cells
    take the two keys left of the table's first column."""
    hi, stacked, body = tbl
    data = [infos[m] for kind, m in body if kind == "data"]
    n_min = int(0.1 * len(data)) if len(data) >= 10 else 0
    cols = _alleys(data, n_min)
    if not cols:
        return None
    head = infos[hi]
    # every heading word to the column it sits over; one over no column is a
    # column of its own (a heading whose values the page leaves blank)
    extra = []
    for w in head["words"] + (infos[stacked[0]]["words"] if stacked else []):
        if _col_for(w, cols) is None:
            extra.append((w["x0"], w["x1"]))
    allc = sorted(cols + extra)
    heads = head["words"] + (infos[stacked[0]]["words"] if stacked else [])
    # a column no heading sits over, separated from its left neighbour by no
    # more than word spacing, is that neighbour's continuation: the alleys
    # inside a description that only one kind of row fills ("HARBOR TOOLS
    # WIREXFER BATCH") are not columns
    named = {_col_for(w, allc) for w in heads}
    merged_c = []
    for k, c in enumerate(allc):
        if merged_c and k not in named and c[0] - merged_c[-1][1] <= gutter:
            merged_c[-1] = (merged_c[-1][0], c[1])
        else:
            merged_c.append(c)
    allc = merged_c
    top_ph, bot_ph = {}, {}
    for w in head["words"]:
        top_ph.setdefault(_col_for(w, allc), []).append(w)
    if stacked:
        for w in infos[stacked[0]]["words"]:
            bot_ph.setdefault(_col_for(w, allc), []).append(w)
    keys = list(range(len(allc)))
    names = [_text(top_ph[k]).casefold() if k in top_ph else "" for k in keys]
    per = _period(names) if len(keys) >= 4 else None
    bands = [keys[b:b + per] for b in range(0, len(keys), per)] if per else [keys]
    band0 = bands[0]
    sheet, used = {}, {}
    for k in band0:
        r = run_of(allc[k][0])
        sub = used.get(r, 0)
        used[r] = sub + 1
        sheet[k] = (r, sub * 2)
    first = sheet[band0[0]][0]
    grouped = any(kind == "group" for kind, _ in body)
    cells, row = [], 0
    hdr_key = _row_key([{"text": head["text"]}])
    if hdr_key not in seen:
        # the header row exactly as printed (rule 7); a heading reprinted on a
        # later page is not written again (rule 11)
        for k in band0:
            if k in top_ph:
                cells.append(_cell(row, sheet[k], top_ph[k], "header"))
            if k in bot_ph:
                r_, s_ = sheet[k]
                cells.append(_cell(row, (r_, s_ + 1), bot_ph[k], "header"))
        row += 1
    seen.add(hdr_key)
    if trace is not None:
        for h in [hi, *stacked]:
            trace.append(("kept", infos[h]["text"]))
    # records: a data line and the lines continuing it (a tail; a stacked
    # table's second line)
    datas = [m for kind, m in body if kind == "data"]
    gaps = [infos[b]["top"] - infos[a]["top"] for a, b in zip(datas, datas[1:])]
    join_gap = None
    if stacked and gaps and max(gaps) > 1.3 * min(gaps):
        join_gap = (min(gaps) + max(gaps)) / 2
    order, cur = [], None
    for kind, m in body:
        li = infos[m]
        if trace is not None and kind != "repeat":
            trace.append(("kept", li["text"]))
        if kind == "repeat":
            continue
        if kind == "data":
            if stacked and cur is not None and cur["open"] and (
                    (join_gap is not None and li["top"] - cur["lines"][-1]["top"] < join_gap)
                    or (join_gap is None and len(cur["lines"]) == 1)):
                cur["lines"].append(li)
                cur["open"] = False
                continue
            cur = {"kind": "rec", "lines": [li], "open": True}
            order.append(cur)
            continue
        if kind == "tail" and cur is not None:
            cur["lines"].append(dict(li, tail=True))
            continue
        cur = None
        order.append({"kind": kind, "li": li})
    out = []
    for item in order:
        if item["kind"] != "rec":
            out.append(item)
            continue
        lines = item["lines"]
        for bi, band in enumerate(bands):
            top_w = {k: [] for k in band}
            bot_w = {k: [] for k in band}
            for n_line, li in enumerate(lines):
                for w in li["words"]:
                    k = _col_for(w, allc)
                    if k not in top_w:
                        continue
                    stacked_line = stacked and n_line >= 1 and not li.get("tail")
                    (bot_w if stacked_line and (band0[band.index(k)] in bot_ph) else top_w)[k].append(w)
            if any(top_w.values()) or any(bot_w.values()):
                out.append({"kind": "rec", "band": bi, "cols": band, "top": top_w,
                            "bot": bot_w})
    if per:
        # side-by-side bands (Run T, 3): read band by band - each top to
        # bottom, then left to right - and sorted by the first column when
        # every band is printed sorted
        recs = sorted((r for r in out if r["kind"] == "rec"), key=lambda r: r["band"])
        rest = [r for r in out if r["kind"] != "rec"]
        ks = [_sort_key(_text(r["top"][r["cols"][0]])) for r in recs]
        if ks and all(k is not None for k in ks):
            by_band = {}
            for r, k in zip(recs, ks):
                by_band.setdefault(r["band"], []).append(k)
            if all(v == sorted(v) for v in by_band.values()):
                recs = [r for _k, r in sorted(zip(ks, recs), key=lambda p: p[0])]
        out = recs + rest
    for item in out:
        kind = item["kind"]
        if kind == "rec":
            for pos, k in enumerate(item["cols"]):
                k0 = band0[pos]
                if item["top"][k]:
                    lab = _text(top_ph[k0]) if k0 in top_ph else None
                    cells.append(_cell(row, sheet[k0], item["top"][k], "value", lab))
                if item["bot"][k]:
                    lab = _text(bot_ph[k0]) if k0 in bot_ph else None
                    r_, s_ = sheet[k0]
                    cells.append(_cell(row, (r_, s_ + 1), item["bot"][k], "value", lab))
            row += 1
        elif kind == "group":
            # Run T, 9: a group line is two facts in two cells (identifier,
            # name), in the two columns left of the table - never in a
            # column of the table, where it would read as one of its values
            li = item["li"]
            ident, name = _group_parts(li)
            iw = li["words"][:len(ident.split())]
            nw = li["words"][len(ident.split()):] or iw
            cells.append(dict(_cell(row, (first, -4), iw, "group", text=ident), bold=True))
            cells.append(dict(_cell(row, (first, -3), nw, "group", text=name), bold=True))
            row += 1
        elif kind == "label":
            # a label line inside the table ("CHECK DATE: 06/24/2026") stays a
            # label/value pair: beside the group cells in a grouped table,
            # where it is printed otherwise
            segs = item["li"]["segs"]
            for n_s, s in enumerate(segs):
                key = ((first, -4) if n_s == 0 else (first, -3)) if grouped \
                    else (run_of(s["x0"]), 0)
                cells.append(_cell(row, key, s["words"],
                                   "label" if s["kind"] == "label" else "value",
                                   text=s["text"]))
            row += 1
    merged = {}
    for c in cells:
        k = (c["row"], c["key"])
        if k in merged:
            merged[k]["text"] += " " + c["text"]
        else:
            merged[k] = c
    # what `_continue_tables` matches a later page's columns by
    role_of = {(first, -4): ("gid", (0.0, 0.0)), (first, -3): ("gname", (0.0, 0.0))}
    for k in band0:
        role_of[sheet[k]] = ("col", allc[k])
        role_of[(sheet[k][0], sheet[k][1] + 1)] = ("bot", allc[k])
    for c in merged.values():
        info = role_of.get(c["key"])
        if info:
            c["_tkey"], c["_role"], c["_x"] = hdr_key, info[0], info[1]
    return {"cells": list(merged.values()), "rows": row, "top": head["top"],
            "bottom": max(infos[m]["bottom"] for _k, m in body)}


def page_cells(page, seen=None, order=None, trace=None, widgets=(), runs=None,
               anchors_out=None, finalize=True):
    """[Cell] for one pdfplumber page; [] when it has no usable text layer.

    `seen`: row keys written on EARLIER pages; a row carrying no figure that
    was written before (a title, a table's heading line, a footer) is not
    written again (rule 11). `order`: the document's day/month order.
    `trace`, when a list, receives (status, text) for every segment read:
    "kept", "prose", "tail", "page_no", "seen" - what `audit` checks.
    `widgets`: a fillable form's typed-in values [{x0, x1, top, bottom,
    value}], placed where the form shows them: beside their labels.
    `runs`: the DOCUMENT's column runs (layout): a table continued on the
    next page then lands in the columns its header was written in.
    `anchors_out` receives this page's column anchors; `finalize=False`
    returns cells still keyed (run, sub), for `_finalize` over all pages."""
    seen = seen if seen is not None else set()
    words = [w for w in _words(page) if not w["markup"]]
    for wd in widgets or ():
        val = re.sub(r"\s+", " ", str(wd.get("value") or "")).strip()
        if val:
            words.append({"text": val, "x0": float(wd["x0"]) + 1.0,
                          "x1": max(float(wd["x0"]) + 2.0, float(wd["x1"])),
                          "top": float(wd["top"]), "bottom": float(wd["bottom"]),
                          "size": 0.0, "bold": False, "italic": False, "markup": False})
    if len(words) < 5:
        return [], "no text layer on this page"
    sizes = [round(w["size"], 1) for w in words if w["size"]]
    body = statistics.mode(sizes) if sizes else 11.0
    for w in words:
        if not w["size"]:
            w["size"] = body
    lines = _lines(words)
    gutter = page_gutter(lines, body)
    rows = []                                    # [(top, [seg], [word])]
    para = None                     # (x0, bottom, height) of the last prose run
    for ln in lines:
        segs, kept = [], []
        for s in _segments(ln, gutter):
            h = max(w["bottom"] - w["top"] for w in s)
            # a paragraph's wrapped lines are prose too, however short: the
            # line directly under a prose line, starting at its left edge,
            # with no label in it ("then shredded.")
            figs = sum(1 for x in _text(s).split() if _is_figure(x))
            tail = (para is not None and 0 <= s[0]["top"] - para[1] <= 1.0 * para[2]
                    and abs(s[0]["x0"] - para[0]) <= 12 and ":" not in _text(s)
                    and figs < 2)
            if _prose(s) or tail:
                para = (s[0]["x0"], max(w["bottom"] for w in s), h)
                if trace is not None:
                    trace.append(("prose" if _prose(s) else "tail", _text(s)))
                continue
            if _PAGE_NO.match(_text(s)) or _furniture(_text(s)):
                if trace is not None:
                    trace.append(("page_no", _text(s)))
                continue                          # rule 12: page furniture
            segs.extend(_split_pairs(_seg(s)))
            kept.extend(s)
        # "Page" and its number printed as two segments
        for a in range(len(segs) - 1):
            if re.fullmatch(r"page\s*:?", segs[a]["text"], re.I) and \
                    re.fullmatch(r"\d+(\s*(of|/)\s*\d+)?", segs[a + 1]["text"]):
                if trace is not None:
                    trace.append(("page_no", segs[a]["text"] + " " + segs[a + 1]["text"]))
                drop = {id(w) for w in segs[a]["words"] + segs[a + 1]["words"]}
                segs = segs[:a] + segs[a + 2:]
                kept = [w for w in kept if id(w) not in drop]
                break
        if segs and _furniture(" ".join(sg["text"] for sg in segs)):
            if trace is not None:
                trace.append(("page_no", " ".join(sg["text"] for sg in segs)))
            continue
        if segs:
            rows.append((kept[0]["top"], segs, kept))
    if not rows:
        return [], "only paragraph text on this page"
    # labels by position: a label's value is the next segment on its line
    for _top, segs, _ln in rows:
        for i, s in enumerate(segs):
            if s["kind"] == "label" and i + 1 < len(segs) and segs[i + 1]["kind"] == "text" \
                    and not segs[i + 1]["text"].endswith(":"):
                segs[i + 1]["kind"] = "value"
    infos = [_line_info(ln, segs) for _t, segs, ln in rows]
    tables = _find_tables(infos)
    in_table = {}
    for t in tables:
        for m in [t[0], *t[1], *(m for _k, m in t[2])]:
            in_table[m] = t
    # the page's column runs: free segments' left edges and the tables'
    # columns, so a table's columns line up with what is printed above them
    anchors = []
    for k, (_t, segs, _ln) in enumerate(rows):
        if k not in in_table:
            anchors += [s["x0"] for s in segs
                        if not (k == 0 and len(segs) == 1 and s["size"] >= 1.3 * body)]
    for t in tables:
        data = [infos[m] for kind, m in t[2] if kind == "data"]
        anchors += [a for a, _b in _alleys(data, int(0.1 * len(data)) if len(data) >= 10 else 0)]
    if anchors_out is not None:
        anchors_out.extend(anchors)
    runs = runs or _columns(anchors, body) or [(0.0, 0.0)]

    def run_of(x):
        return _col_of(x, runs)
    width = float(page.width)
    rules = _rules(page)
    thick = _thick(rules, width)

    def _bottom(segs):
        return max(w["bottom"] for sg in segs for w in sg["words"])
    items, done = [], set()
    for k, (top, segs, _ln) in enumerate(rows):
        if k in in_table:
            t = in_table[k]
            if id(t) not in done:
                done.add(id(t))
                em = _emit_table(t, infos, run_of, trace, seen, gutter)
                if em is not None:
                    items.append(("table", em["top"], em["bottom"], em))
            continue
        items.append(("free", top, _bottom(segs), (k, segs)))
    # rule 3: spacing is the WHITE space between lines, against the page's
    # usual white space
    white = [b[1] - a[2] for a, b in zip(items, items[1:])]
    usual = statistics.median([w for w in white if w > 0] or [body * 0.5])
    cells, out_row = [], 0
    prev_top, prev_bottom, prev_cells = None, None, []
    for kind, top, bottom, obj in items:
        if kind == "table":
            if prev_bottom is not None and top - prev_bottom > _BLANK_PITCH * usual:
                out_row += 1
            for c in obj["cells"]:
                c["row"] += out_row
                c["size"] = sheet_size(c.pop("_size"), body)
                if c["kind"] == "header":
                    c["bold"], c["align"] = True, "center"
            cells.extend(obj["cells"])
            out_row += obj["rows"]
            prev_top, prev_bottom, prev_cells = None, bottom, []
            continue
        k, segs = obj
        key = _row_key(segs)
        if key in seen and not any(_is_figure(x) for sg in segs for x in sg["text"].split()):
            if trace is not None:
                trace += [("seen", sg["text"]) for sg in segs]
            continue                              # rule 11: written on a page before
        if trace is not None:
            trace += [("kept", " ".join(w["text"] for w in sg["words"])) for sg in segs]
        seen.add(key)
        # continuation of the values directly above (rule 5)
        if prev_cells and prev_top is not None and top - prev_top <= 1.4 * max(
                s["size"] for s in segs) and all(s["kind"] == "text" for s in segs):
            above = {c["key"]: c for c in prev_cells if c["kind"] == "value"}
            ks = [(run_of(s["x0"]), 0) for s in segs]
            if ks and all(c in above for c in ks):
                for s, c in zip(segs, ks):
                    above[c]["text"] += " " + s["text"]
                prev_top, prev_bottom = top, _bottom(segs)
                continue
        if prev_bottom is not None and top - prev_bottom > _BLANK_PITCH * usual:
            out_row += 1                          # one blank row, never more
        row_cells = []
        title = (k == 0 and len(segs) == 1 and segs[0]["size"] >= 1.3 * body)
        lab = None
        for s in segs:
            centre = (s["x0"] + s["x1"]) / 2
            centred_on_page = abs(centre - width / 2) <= 0.03 * width
            # rule 15: a line that is one segment centred on the page is centred
            centred = centred_on_page and len(segs) == 1
            col = run_of(centre if title and centred_on_page else s["x0"])
            # Run T, 10: two printed items sharing a page run are two cells
            # (a label and its value, two pairs) - never glued into one
            sub = sum(1 for c in row_cells if c["key"][0] == col)
            row_cells.append({"row": out_row, "key": (col, sub), "text": s["text"],
                              "kind": "title" if title else s["kind"],
                              "bold": s["bold"], "italic": s["italic"],
                              "underline": _underlined(s, rules),
                              "size": sheet_size(s["size"], body),
                              "align": "center" if centred else None,
                              "_bottom": _bottom([s]),
                              "_label": lab if s["kind"] == "value" else None})
            lab = s["text"] if s["kind"] == "label" else None
        cells.extend(row_cells)
        prev_top, prev_bottom, prev_cells = top, _bottom(segs), row_cells
        out_row += 1
    if not cells:
        return [], "only paragraph text on this page"
    # rule 14: a thick rule under a row gives that row a thick bottom border
    # (the row directly above the rule: the lowest row whose bottom is above it)
    for y in thick:
        above = [c for c in cells if c["_bottom"] <= y + 1.0]
        if not above:
            continue
        r = max(c["row"] for c in above)
        for c in cells:
            if c["row"] == r:
                c["border_bottom"] = "thick"
    if not finalize:
        return cells, None
    return _finalize(cells, order, {k: i for i, k in enumerate(sorted({c["key"] for c in cells}))}), None


def _finalize(cells, order, col_of_key):
    """Sheet columns from the (run, sub) keys, then everything that reads a
    column: header rows, identifier columns, typed values."""
    for c in cells:
        c["col"] = col_of_key[c.pop("key")]
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
    # Run T, 8: a column holding a zero-padded identifier ("0025") is a
    # column of identifiers - every digit run in it stays text
    by_col = {}
    for c in cells:
        if c["kind"] in ("value", "text"):
            by_col.setdefault(c["col"], []).append(c)
    text_cols = {col for col, cs in by_col.items()
                 if any(re.fullmatch(r"0\d+", c["text"].strip()) for c in cs)}
    for c in cells:
        label = c.pop("_label", None)
        c.pop("_bottom", None)
        if c["kind"] in ("value", "text"):
            if c["col"] in text_cols and re.fullmatch(r"\d+", c["text"].strip()):
                c["value"], c["number_format"] = c["text"].strip(), None
            else:
                c["value"], c["number_format"] = typed(c["text"], order, label)
        else:
            c["value"], c["number_format"] = c["text"], None
    return cells


def _document_order(pdf):
    """The document's day/month order from its own unambiguous dates."""
    import dates as D
    texts = []
    for page in pdf.pages:
        try:
            texts += [w["text"] for w in page.extract_words()
                      if re.match(r"^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$", w["text"])]
        except Exception:
            continue
    return D.document_order(texts)[0]


def _widget_values(pdf_path) -> dict:
    """A fillable form's typed-in values per page index (text_layer)."""
    try:
        from text_layer import acroform_field_values
        return acroform_field_values(pdf_path) or {}
    except Exception:
        return {}


def layout(pdf_path) -> dict:
    import pdfplumber
    pages, skipped = [], []
    seen = set()
    widgets = _widget_values(pdf_path)
    with pdfplumber.open(str(pdf_path)) as pdf:
        order = _document_order(pdf)
        tables = {}
        for n, page in enumerate(pdf.pages, 1):
            cells, why = page_cells(page, seen, order, widgets=widgets.get(n - 1, ()))
            if why:
                skipped.append(f"page {n}: {why}")
            if cells:
                pages.append(_continue_tables(cells, tables))
    return {"pages": pages, "skipped": skipped, "text_layer": bool(pages)}


def _continue_tables(cells, tables):
    """A table whose heading was written on an earlier page keeps that
    page's sheet columns: each of its cells moves to the column of the
    earlier table whose x span it overlaps most, so page 2's amounts sit
    under page 1's "Debits", never one column off. `tables`: heading key ->
    {role: [(x0, x1, col)]}, filled from each table's first page."""
    by_key = {}
    for c in cells:
        if c.get("_tkey") is not None:
            by_key.setdefault(c["_tkey"], []).append(c)
    for key, cs in by_key.items():
        if key not in tables:
            got = {}
            for c in cs:
                got.setdefault(c["_role"], {})[(c["_x"][0], c["_x"][1])] = c["col"]
            tables[key] = {r: [(a, b, col) for (a, b), col in v.items()] for r, v in got.items()}
            continue
        for c in cs:
            spans = tables[key].get(c["_role"]) or []
            if not spans:
                continue
            a, b = c["_x"]
            best = max(spans, key=lambda s: (min(b, s[1]) - max(a, s[0]),
                                             -abs((a + b) / 2 - (s[0] + s[1]) / 2)))
            c["col"] = best[2]
    for c in cells:
        for k in ("_tkey", "_role", "_x"):
            c.pop(k, None)
    return cells


def audit(pdf_path):
    """Rule 17 self-check: every figure of a segment the layout KEPT (not
    prose, not a paragraph's tail, not a page number, not a heading written
    on an earlier page) reaches a cell of its page. {"lost": [(page, token)],
    "pages": n, "dropped": {status: n}} or None when no page has a text
    layer. Uses page_cells' own record, so it can never disagree with the
    layout about what was meant to be copied."""
    import pdfplumber
    lost, dropped, laid = [], {}, 0
    seen = set()
    with pdfplumber.open(str(pdf_path)) as pdf:
        order = _document_order(pdf)
        widgets = _widget_values(pdf_path)
        for n, page in enumerate(pdf.pages, 1):
            trace = []
            cells, _why = page_cells(page, seen, order, trace, widgets.get(n - 1, ()))
            if not cells:
                continue
            laid += 1
            flat = " ".join(c["text"] for c in cells).replace(" ", "")
            for status, text in trace:
                if status != "kept":
                    dropped[status] = dropped.get(status, 0) + 1
                    continue
                for tok in text.split():
                    tok = tok.strip(".,;:")
                    if re.search(r"\d", tok) and len(re.sub(r"\D", "", tok)) >= 2 \
                            and tok.replace(" ", "") not in flat:
                        lost.append((n, tok))
    if not laid:
        return None
    return {"lost": lost, "pages": laid, "dropped": dropped}
