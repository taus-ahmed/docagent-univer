"""Perception (Run T1, Stage 2): a page as words with boxes, read by code.

One contract, the same for every reader, and NO model:

    word  {id, text, x0, x1, top, bottom, baseline, size, font, bold, italic,
           color, rotation, page, origin}
    line  {id, page, word_ids, text, x0, x1, top, bottom, baseline, size}

``origin`` is ``text`` (the PDF's text layer), ``widget`` (a fillable form's
value or checkbox state, 2e) or ``ocr``. Rotation is in degrees, counter-
clockwise, from the character matrix. Colour is the fill colour as printed
(grey, RGB or CMYK components).

Per page the layer also says how far its text layer can be trusted
(`quality`, 2a) and which words it took out as background and why
(`removed`, 2d). The extraction path's own reader (`text_layer.read_page`)
is NOT changed by this module: its text is part of every prompt and every
cached answer. This is the reading the structure engine (Stage 3) and the
Organized export use, and that the job stores per document (2f) so an export
can be rebuilt without the uploaded file.
"""
from __future__ import annotations

import base64
import json
import math
import re
import statistics
import zlib
from typing import Optional

PERCEPTION_VERSION = 1

# ── 2b normalisation ─────────────────────────────────────────────────────────

_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-")
_SPACES = dict.fromkeys(map(ord, "\u00a0\u2007\u202f\u2009\u200a\u2002\u2003\u2004\u2005\u2006\u3000"), " ")
_ZERO = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"), None)
_LIGS = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
         "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"}


def normalise(s) -> str:
    """The printed characters in one notation: every dash variant a hyphen,
    every fixed-width or non-breaking space a space, ligatures spelled out,
    zero-width characters and soft hyphens gone. Letters, digits and their
    order are never changed."""
    t = str(s or "")
    for k, v in _LIGS.items():
        t = t.replace(k, v)
    return t.translate(_DASHES).translate(_SPACES).translate(_ZERO)


def loose_key(s) -> str:
    """`s` with whitespace AND punctuation removed, case folded: the key two
    renderings of one printed run share ("WIREOUT" / "WIRE OUT" /
    "WIRE-OUT")."""
    return "".join(ch for ch in normalise(s).casefold() if ch.isalnum())


def loose_find(needle, hay, min_chars: int = 4) -> Optional[str]:
    """The run of `hay` that spells `needle` once whitespace and punctuation
    are ignored, starting and ending at token boundaries; None when there is
    none or the needle is shorter than `min_chars` alphanumerics (a short
    fragment must not hit by chance)."""
    key = loose_key(needle)
    if len(key) < min_chars:
        return None
    h = normalise(hay)
    pat = (r"(?<![0-9A-Za-z])" + r"[\W_]*".join(re.escape(ch) for ch in key)
           + r"(?![0-9A-Za-z])")
    m = re.search(pat, h, re.I)
    return m.group(0) if m else None


_SIGNED = re.compile(r"^\(?[$€£¥₹]?\d[\d,.\s]*\)?-$")


def trailing_minus(tok) -> bool:
    """`26.08-`: a figure printed with its sign AFTER it (a negative)."""
    return bool(_SIGNED.match(normalise(tok).strip()))


# ── words ────────────────────────────────────────────────────────────────────

def _rotation(matrix) -> float:
    m = matrix or (1, 0, 0, 1, 0, 0)
    try:
        return round(math.degrees(math.atan2(float(m[1]), float(m[0]))) % 360, 1)
    except (TypeError, ValueError, IndexError):
        return 0.0


def orthogonal(rot: float, tol: float = 3.0) -> bool:
    r = float(rot or 0) % 90
    return r <= tol or r >= 90 - tol


def _color(c):
    v = c.get("non_stroking_color")
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return [round(float(v), 3)]
    try:
        return [round(float(x), 3) for x in v]
    except (TypeError, ValueError):
        return None


def light(color, threshold: float = 0.8) -> bool:
    """A very pale fill: grey/RGB every channel >= threshold, CMYK every ink
    <= 1 - threshold. Unknown: not light."""
    if not color:
        return False
    if len(color) == 4:
        return all(v <= 1 - threshold for v in color)
    return all(v >= threshold for v in color)


def _font_flags(font: str):
    f = str(font or "").split("+")[-1].casefold()
    return ("bold" in f or "black" in f or "heavy" in f or "semibold" in f,
            "italic" in f or "oblique" in f)


def _word_from_chars(chars, page_no, origin="text"):
    text = "".join(str(c.get("text", "")) for c in chars)
    sizes = [float(c.get("size") or 0) for c in chars]
    font = max((str(c.get("fontname") or "") for c in chars), key=lambda f: sum(
        1 for c in chars if str(c.get("fontname") or "") == f), default="")
    bold, italic = _font_flags(font)
    cols = [tuple(_color(c) or ()) for c in chars]
    color = list(max(set(cols), key=cols.count)) if cols else None
    return {"text": text,
            "x0": round(min(float(c["x0"]) for c in chars), 2),
            "x1": round(max(float(c["x1"]) for c in chars), 2),
            "top": round(min(float(c["top"]) for c in chars), 2),
            "bottom": round(max(float(c["bottom"]) for c in chars), 2),
            "baseline": round(statistics.median(float(c["bottom"]) for c in chars), 2),
            "size": round(statistics.median(sizes), 2) if sizes else 0.0,
            "font": font, "bold": bold, "italic": italic,
            "color": color or None,
            "rotation": _rotation(chars[0].get("matrix")),
            "page": page_no, "origin": origin}


def _upright(rot) -> bool:
    r = float(rot or 0) % 360
    return r <= 3 or r >= 357


def _rotated_runs(chars):
    """Characters NOT printed upright (diagonal, or a quarter turn), grouped
    into runs of one direction and split into words at spaces. Horizontal
    grouping cannot read them: it shreds a sideways heading into letters."""
    runs, cur, key = [], [], None
    for c in chars:
        rot = _rotation(c.get("matrix"))
        k = None if _upright(rot) else round(rot)
        if k is not None and k == key:
            cur.append(c)
            continue
        if cur:
            runs.append(cur)
        cur, key = ([c], k) if k is not None else ([], None)
    if cur:
        runs.append(cur)
    words = []
    for r in runs:
        w = []
        for c in r:
            if str(c.get("text", "")).strip():
                w.append(c)
            elif w:
                words.append(w)
                w = []
        if w:
            words.append(w)
    return words


def page_words(page, page_no: int) -> list:
    """Every word on a pdfplumber page with its box, font, size, colour and
    rotation. Upright text is grouped by pdfplumber (size-aware, so texts at
    different sizes never merge into one word, I10); text at a NON-
    orthogonal angle is grouped by run, since horizontal grouping cannot
    read it."""
    chars = list(getattr(page, "chars", None) or [])
    diag = _rotated_runs(chars)
    diag_ids = {id(c) for r in diag for c in r}
    out = []
    upright_page = page.filter(lambda o: id(o) not in diag_ids) if diag_ids else page
    try:
        ws = upright_page.extract_words(extra_attrs=["size", "fontname"],
                                        return_chars=True, keep_blank_chars=False)
    except TypeError:
        ws = upright_page.extract_words(return_chars=True)
    for w in ws:
        ch = [c for c in (w.get("chars") or []) if str(c.get("text", "")).strip()]
        if not ch:
            continue
        word = _word_from_chars(ch, page_no)
        word["text"] = w.get("text") or word["text"]
        out.append(word)
    for r in diag:
        out.append(_word_from_chars(r, page_no))
    return out


# ── 2c lines by baseline ─────────────────────────────────────────────────────

def lines_of(words) -> list:
    """Words grouped into printed lines by BASELINE, with a tolerance of a
    third of the body size, upright text only, left to right. A line made
    only of words much smaller than the line just below it, sitting within
    that line's height above its baseline and over its x span, is that
    line's superscripts (`sup`), kept as their own tokens on it. Text not
    printed upright is a line per word (a side caption, a sideways
    heading)."""
    up = [w for w in words if _upright(w.get("rotation", 0))]
    other = [w for w in words if not _upright(w.get("rotation", 0))]
    sizes = [w["size"] for w in up if w.get("size")]
    body = statistics.median(sizes) if sizes else 10.0
    tol = max(1.0, body / 3)
    up.sort(key=lambda w: (w["baseline"], w["x0"]))
    lines, cur = [], []
    for w in up:
        if cur and abs(w["baseline"] - statistics.median(x["baseline"] for x in cur)) > tol:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    merged, i = [], 0
    while i < len(lines):
        ln = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if nxt:
            ref = statistics.median(x["baseline"] for x in nxt)
            ref_size = statistics.median(x.get("size") or body for x in nxt)
            x0, x1 = min(x["x0"] for x in nxt), max(x["x1"] for x in nxt)
            if all((w.get("size") or body) < 0.8 * ref_size
                   and ref - ref_size <= w["baseline"] < ref
                   and x0 <= w["x0"] <= x1 for w in ln):
                for w in ln:
                    w["sup"] = True
                lines[i + 1] = nxt + ln
                i += 1
                continue
        merged.append(ln)
        i += 1
    out = [sorted(ws, key=lambda w: w["x0"]) for ws in merged]
    for w in other:
        out.append([w])
    out.sort(key=lambda ws: (min(w["top"] for w in ws), min(w["x0"] for w in ws)))
    return out


def side_zone(words, width: float) -> Optional[float]:
    """The x of a vertical alley that separates a SIDE PANEL from the main
    content, or None. All of these, because a false side panel would hide
    a real column:

      * no word crosses it, and it is at least 2x the gutter wide;
      * the side beyond it is at the margin and narrow (under 35% of the
        page width), holds 3+ words over at least half the content's height;
      * the side has rows of its OWN: under 30% of its words share a
        baseline with a word of the main content (a table's last column
        shares every row's baseline, and so is never a side panel)."""
    ws = [w for w in words if _upright(w.get("rotation", 0))]
    if len(ws) < 10 or not width:
        return None
    sizes = [w["size"] for w in ws if w.get("size")]
    body = statistics.median(sizes) if sizes else 10.0
    min_alley = 2 * max(6.0, 4 * 0.35 * body)
    top = min(w["top"] for w in ws)
    span = max(max(w["bottom"] for w in ws) - top, 1)
    best = None
    for side in ("right", "left"):
        # candidate alleys: gaps in the x coverage
        spans = sorted((w["x0"], w["x1"]) for w in ws)
        cur, gaps = spans[0][1], []
        for a, b in spans[1:]:
            if a - cur >= min_alley:
                gaps.append((cur, a))
            cur = max(cur, b)
        for a, b in gaps:
            x = (a + b) / 2
            narrow = [w for w in ws if (w["x0"] >= x if side == "right" else w["x1"] <= x)]
            main = [w for w in ws if w not in narrow]
            zone_w = (width - b) if side == "right" else a
            if not main or len(narrow) < 3 or zone_w > 0.35 * width:
                continue
            nspan = max(w["bottom"] for w in narrow) - min(w["top"] for w in narrow)
            if nspan < 0.5 * span:
                continue
            base = [w["baseline"] for w in main]
            shared = sum(1 for w in narrow if any(abs(w["baseline"] - y) <= 1.5 for y in base))
            if shared >= 0.3 * len(narrow):
                continue
            best = x
            break
        if best is not None:
            break
    return best


def line_record(ws, lid, page_no) -> dict:
    return {"id": lid, "page": page_no, "word_ids": [w["id"] for w in ws],
            "text": " ".join(w["text"] for w in ws),
            "x0": min(w["x0"] for w in ws), "x1": max(w["x1"] for w in ws),
            "top": min(w["top"] for w in ws), "bottom": max(w["bottom"] for w in ws),
            "baseline": statistics.median(w["baseline"] for w in ws),
            "size": statistics.median(w.get("size") or 0 for w in ws)}


def stacked_cells(lines, max_gap_ratio: float = 0.6) -> list:
    """(upper line id, lower line id) where a run of words sits DIRECTLY
    above another inside the same x span - one cell printed on two lines
    (`Tran` over `Date`, `Total` over `Amount`). The pair must overlap in x
    by at least half the narrower run, and its gap must be under
    `max_gap_ratio` of the text size AND under half the page's usual gap
    between lines, so ordinary single-spaced text is not read as stacked."""
    gaps = [b["top"] - a["bottom"] for a, b in zip(lines, lines[1:])]
    usual = statistics.median(gaps) if gaps else 0.0
    out = []
    for (a, b), gap in zip(zip(lines, lines[1:]), gaps):
        size = max(a.get("size") or 0, b.get("size") or 0) or 10
        if gap < -0.3 * size or gap > max_gap_ratio * size or gap > 0.5 * usual:
            continue
        ov = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
        if ov < 0.5 * min(a["x1"] - a["x0"], b["x1"] - b["x0"]):
            continue
        out.append((a["id"], b["id"]))
    return out


# ── 2a quality ───────────────────────────────────────────────────────────────

_GARBLE = re.compile(r"\(cid:\d+\)|[\ufffd\ue000-\uf8ff]")


def quality(page, words) -> dict:
    """How far the text layer can be trusted on this page, 0..1, and the
    reader it chooses. Signals: garbled glyphs (`(cid:n)`, U+FFFD, private
    use), letter runs with no vowel (an encoding without a usable map),
    text drawn as OUTLINES (many curves, few characters), and image regions
    with no word over them (printed as a picture). `source` is `text` when
    the score is at least 0.7 and the page has words, else `ocr`;
    `ocr_regions` are image boxes with no text inside, to be read by OCR
    even on a text page."""
    n = len(words)
    garbled = sum(1 for w in words if _GARBLE.search(w["text"]))
    alpha = [w for w in words if re.fullmatch(r"[A-Za-z]{5,}", w["text"])]
    novowel = sum(1 for w in alpha if not re.search(r"[aeiouyAEIOUY]", w["text"]))
    curves = len(getattr(page, "curves", None) or [])
    area = float(page.width or 1) * float(page.height or 1)
    regions = []
    for im in getattr(page, "images", None) or []:
        box = (float(im["x0"]), float(im["top"]), float(im["x1"]), float(im["bottom"]))
        a = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
        if a < 0.05 * area:
            continue
        inside = sum(1 for w in words if w["x0"] >= box[0] and w["x1"] <= box[2]
                     and w["top"] >= box[1] and w["bottom"] <= box[3])
        if inside < 3:
            regions.append({"x0": box[0], "top": box[1], "x1": box[2],
                            "bottom": box[3]})
    outlined = curves >= 300 and n < 20
    bad = (garbled / n if n else 1.0)
    bad = max(bad, (novowel / len(alpha)) if len(alpha) >= 5 else 0.0)
    image_share = sum((r["x1"] - r["x0"]) * (r["bottom"] - r["top"]) for r in regions) / area
    score = max(0.0, 1.0 - bad - (0.5 if outlined else 0.0) - 0.5 * min(image_share, 1.0))
    if n == 0:
        score = 0.0
    return {"score": round(score, 3), "words": n, "garbled": garbled,
            "no_vowel_runs": novowel, "outlined": outlined,
            "image_share": round(image_share, 3),
            "source": "text" if (n and score >= 0.7) else "ocr",
            "ocr_regions": regions}


# ── 2d background ────────────────────────────────────────────────────────────

def _overlaps(a, b) -> bool:
    return a["x0"] < b["x1"] and b["x0"] < a["x1"] and a["top"] < b["bottom"] and \
        b["top"] < a["bottom"]


def _protected_lines(lines, words_by_id) -> set:
    """Word ids on lines that are a label/value pair or a table row: never
    background, whatever they look like."""
    keep = set()
    amount = re.compile(r"\d[\d,]*\.\d{2}\b|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b")
    for ln in lines:
        t = ln["text"]
        if re.search(r"\S:\s*\S", t) or len(amount.findall(t)) >= 2:
            keep.update(ln["word_ids"])
    return keep


def background(pages: list) -> dict:
    """{page index: [(word id, [signals])]} - words to suppress as watermark
    or background. A word is suppressed only with AT LEAST TWO signals:

      rotated_large   at a non-orthogonal angle AND at least 1.8x the body size
      faint           a very light fill colour
      repeated        the same text at the same position (within 2% of the page)
                      on two or more pages
      behind          its box overlaps other words (drawn under or over content)

    and never when it is on a line that is a label/value pair or a table
    row, nor when another word on its own line does not qualify. A quarter-turn column heading or a vertical side caption is
    orthogonal, so it can never be `rotated_large`, and is kept unless two
    OTHER signals agree."""
    out = {}
    sigs = {}
    pos = {}
    for pi, pg in enumerate(pages):
        for w in pg["words"]:
            k = (loose_key(w["text"]),
                 round(w["x0"] / max(pg["width"], 1) * 50),
                 round(w["top"] / max(pg["height"], 1) * 50))
            if k[0]:
                pos.setdefault(k, set()).add(pi)
    for pi, pg in enumerate(pages):
        words = pg["words"]
        sizes = [w["size"] for w in words if w.get("size") and orthogonal(w["rotation"])]
        body = statistics.median(sizes) if sizes else 10.0
        by_id = {w["id"]: w for w in words}
        protected = _protected_lines(pg.get("lines") or [], by_id)
        for w in words:
            s = []
            if not orthogonal(w["rotation"]) and (w.get("size") or 0) >= 1.8 * body:
                s.append("rotated_large")
            if light(w.get("color")) and not w.get("on_dark_fill"):
                # pale text on a dark filled box (a header bar) is high
                # contrast, not faint
                s.append("faint")
            k = (loose_key(w["text"]),
                 round(w["x0"] / max(pg["width"], 1) * 50),
                 round(w["top"] / max(pg["height"], 1) * 50))
            if len(pages) >= 2 and len(pos.get(k, ())) >= 2 and (
                    not orthogonal(w["rotation"]) or light(w.get("color"))):
                # a repeated footer is furniture, not background: repetition
                # only counts for text that also LOOKS like decoration
                s.append("repeated")
            if any(o is not w and _overlaps(w, o) for o in words):
                s.append("behind")
            if len(s) >= 2 and w["id"] not in protected:
                sigs.setdefault(pi, []).append((w["id"], s))
        # background is a whole printed run: a word is removed only when
        # every word on its line is (grey explanatory text repeated on each
        # page keeps its sentence; it is never cut into fragments)
        hit = {wid for wid, _s in sigs.get(pi, [])}
        for ln in pg.get("lines") or []:
            if any(i in hit for i in ln["word_ids"]) and                     not all(i in hit for i in ln["word_ids"]):
                hit -= set(ln["word_ids"])
        if pi in sigs:
            sigs[pi] = [(wid, s) for wid, s in sigs[pi] if wid in hit]
            if not sigs[pi]:
                del sigs[pi]
    out.update(sigs)
    return out


# ── 2e form fields ───────────────────────────────────────────────────────────

def widget_words(path, page_no: int, height: float = 0.0) -> list:
    """Fillable-form values and checkbox states as words at the widget's
    position: a text field's value as typed, a checked box `[X]`, an
    unchecked one `[ ]`. Top-left points, like the text layer."""
    try:
        from text_layer import acroform_field_values, acroform_widgets
        boxes = (acroform_widgets(path) or {}).get(page_no - 1, [])
        fields = (acroform_field_values(path) or {}).get(page_no - 1, [])
    except Exception:
        return []
    out = []
    for w, text in [(b, "[X]" if b.get("on") else "[ ]") for b in boxes] +             [(f, str(f.get("value") or "").strip()) for f in fields]:
        if not text:
            continue
        top, bottom = float(w["top"]), float(w["bottom"])
        size = max(6.0, min(14.0, (bottom - top) * 0.7))
        out.append({"text": text, "x0": round(float(w["x0"]), 2),
                    "x1": round(float(w["x1"]), 2),
                    "top": round(top, 2), "bottom": round(bottom, 2),
                    "baseline": round(bottom - 0.2 * size, 2), "size": round(size, 2),
                    "font": "", "bold": False, "italic": False, "color": None,
                    "rotation": 0.0, "page": page_no, "origin": "widget",
                    "field": w.get("name") or None,
                    "checkbox": text in ("[X]", "[ ]")})
    return out


# ── the document ─────────────────────────────────────────────────────────────

def read_document(path, pages: Optional[list] = None) -> dict:
    """The perception of a PDF: per page its words, lines, quality and the
    words removed as background (with reasons). `pages` are 1-based file
    page numbers to read (default all)."""
    import pdfplumber
    doc = {"version": PERCEPTION_VERSION, "pages": []}
    with pdfplumber.open(str(path)) as pdf:
        nums = pages or list(range(1, len(pdf.pages) + 1))
        for n in nums:
            if not 1 <= n <= len(pdf.pages):
                continue
            pg = pdf.pages[n - 1]
            words = page_words(pg, n) + widget_words(path, n, float(pg.height))
            _mark_fills(pg, words)
            for i, w in enumerate(words):
                w["id"] = f"p{n}w{i}"
            q = quality(pg, [w for w in words if w["origin"] == "text"])
            doc["pages"].append({"page": n, "width": float(pg.width),
                                 "height": float(pg.height), "words": words,
                                 "quality": q, "removed": [],
                                 "rules": _rules(pg)})
    for p in doc["pages"]:
        p["side_split"] = side_zone(p["words"], p["width"])
        p["lines"] = _lines_for(p["words"], p["page"], p["side_split"])
    bg = background(doc["pages"])
    for pi, hits in bg.items():
        p = doc["pages"][pi]
        gone = {wid for wid, _s in hits}
        by_id = {w["id"]: w for w in p["words"]}
        p["removed"] = [{"id": wid, "text": by_id[wid]["text"], "reasons": s,
                         "box": [by_id[wid]["x0"], by_id[wid]["top"],
                                 by_id[wid]["x1"], by_id[wid]["bottom"]]}
                        for wid, s in hits]
        p["words"] = [w for w in p["words"] if w["id"] not in gone]
        p["side_split"] = side_zone(p["words"], p["width"])
        p["lines"] = _lines_for(p["words"], p["page"], p["side_split"])
    return doc


def _lines_for(words, page_no, split=None):
    """Lines, formed separately on each side of a side-panel alley so a
    side note never joins the table row it happens to share a baseline
    with."""
    if split is None:
        groups = lines_of(words)
    else:
        groups = lines_of([w for w in words if w["x1"] <= split]) +             lines_of([w for w in words if w["x1"] > split])
        groups.sort(key=lambda ws: (min(w["top"] for w in ws), min(w["x0"] for w in ws)))
    return [line_record(ws, f"p{page_no}l{i}", page_no) for i, ws in enumerate(groups)]


def _mark_fills(page, words) -> None:
    """`on_dark_fill` on every word whose centre lies on a filled shape that
    is not light (white text on a coloured header bar)."""
    fills = []
    for r in getattr(page, "rects", None) or []:
        if not r.get("fill"):
            continue
        col = r.get("non_stroking_color")
        col = [float(col)] if isinstance(col, (int, float)) else             [float(x) for x in col] if isinstance(col, (list, tuple)) else None
        if col and not light(col, 0.6):
            fills.append((float(r["x0"]), float(r["top"]), float(r["x1"]),
                          float(r["bottom"])))
    if not fills:
        return
    for w in words:
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        if any(x0 <= cx <= x1 and t <= cy <= b for x0, t, x1, b in fills):
            w["on_dark_fill"] = True


def _rules(page) -> list:
    """Horizontal strokes (lines, thin rectangles): [x0, x1, y, thickness]."""
    out = []
    for ln in getattr(page, "lines", None) or []:
        if abs(float(ln["top"]) - float(ln["bottom"])) < 1.0:
            out.append([round(float(ln["x0"]), 1), round(float(ln["x1"]), 1),
                        round(float(ln["top"]), 1),
                        round(float(ln.get("linewidth") or 1), 2)])
    for r in getattr(page, "rects", None) or []:
        h = float(r["bottom"]) - float(r["top"])
        if 0 < h <= 3.0 and float(r["x1"]) - float(r["x0"]) > 3 * h:
            out.append([round(float(r["x0"]), 1), round(float(r["x1"]), 1),
                        round(float(r["top"]), 1), round(h, 2)])
    return out


# ── 2f storage ───────────────────────────────────────────────────────────────

def pack(doc: dict) -> str:
    """A perception as compact text for the database: `pz1:` + base64 of
    zlib-compressed JSON."""
    raw = json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "pz1:" + base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def unpack(s) -> Optional[dict]:
    if not s:
        return None
    s = str(s)
    try:
        if s.startswith("pz1:"):
            return json.loads(zlib.decompress(base64.b64decode(s[4:])).decode("utf-8"))
        return json.loads(s)
    except (ValueError, zlib.error):
        return None
