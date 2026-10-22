"""Several cheques on ONE scanned page -> one region per cheque (Gate 4b, option 2).

A document is a run of whole pages, so a page carrying two or three cheques
was one document: one slot set asked of several cheques, the model answering
for one of them, the others with no record at all. Splitting PAGES cannot help;
the page itself has to be cut.

THE ANCHOR IS THE MICR BAND. Every cheque prints exactly one, along its
bottom edge, and on both multi-up fixture pages OCR found exactly one band per
cheque. A cheque's region is everything above its own band and below the
previous one in its column; side by side, the column boundary is the widest
EMPTY vertical gutter between the two bands' rows — paper between two cheques
is the one x-range no line of either crosses.

Anchors are found at WORD level, so two bands Tesseract reads into one line
(cheques side by side) are still two anchors, and a band whose digits did not
survive (`A423S11G18A`) still anchors by its shape — its cheque gets a region
of its own instead of vanishing into its neighbour's.

FAIL CLOSED. Anything that would make the cut a guess — fewer than two bands,
two readable bands that could be one cheque, no empty gutter between cheques
side by side, a region too small to be a cheque — returns no regions and a
reason; the page stays ONE record, which is flagged
`possible_multiple_documents` downstream. Never a silent merge, never a drop.

Coordinates are never transformed: every box and word stays in the frame of
the STRAIGHTENED image the reader saw, which is also the image the region's
crop is taken from.
"""
from __future__ import annotations

from micr import _LOOSE_TRANSIT, _SHAPED_TRANSIT, band_identity, same_band

#: A region with fewer words than this is not a cheque; cutting there would
#: invent a document from a fragment.
MIN_REGION_WORDS = 8
#: The narrowest empty vertical strip accepted as the paper between two
#: cheques side by side, in reader pixels (300 dpi: ~1.3 mm).
MIN_GUTTER_PX = 15.0


def _line_text(line):
    """(text, [(start, end, word)]) — the line as one string, with each
    word's character span, so a regex match maps back to word geometry."""
    parts, spans, at = [], [], 0
    for w in line:
        t = str(w.get("text") or "")
        if parts:
            at += 1
        spans.append((at, at + len(t), w))
        parts.append(t)
        at += len(t)
    return " ".join(parts), spans


def find_anchors(lines):
    """Every MICR transit field on a page, as geometry plus identity.

    [{"x0", "x1", "top", "bottom", "identity"}] — `identity` is {} for a
    band-shaped field whose digits could not be read.
    """
    out = []
    for line in lines or []:
        text, spans = _line_text(line)
        matches = list(_LOOSE_TRANSIT.finditer(text))
        taken = [(m.start(), m.end()) for m in matches]
        matches += [m for m in _SHAPED_TRANSIT.finditer(text)
                    if not any(a < m.end() and m.start() < b for a, b in taken)
                    and sum(c.isdigit() for c in text) >= 10]
        matches.sort(key=lambda m: m.start())
        for k, m in enumerate(matches):
            words = [w for a, b, w in spans if a < m.end() and m.start() < b]
            if not words:
                continue
            end = matches[k + 1].start() if k + 1 < len(matches) else len(text)
            out.append({"x0": min(float(w["x0"]) for w in words),
                        "x1": max(float(w["x1"]) for w in words),
                        "top": min(float(w["top"]) for w in words),
                        "bottom": max(float(w["bottom"]) for w in words),
                        "identity": band_identity(text[m.start():end])})
    return out


def _rows(anchors):
    """Anchors grouped into rows of cheques side by side, top to bottom."""
    rows = []
    for a in sorted(anchors, key=lambda a: a["top"]):
        row = rows[-1] if rows else None
        if row and any(a["top"] < b["bottom"] and b["top"] < a["bottom"] for b in row):
            row.append(a)
        else:
            rows.append([a])
    return [sorted(r, key=lambda a: a["x0"]) for r in rows]


def _gutter(words, lo, hi):
    """Centre of the widest x-range in (lo, hi) that no word covers, or None."""
    spans = sorted((max(lo, float(w["x0"])), min(hi, float(w["x1"])))
                   for w in words if float(w["x1"]) > lo and float(w["x0"]) < hi)
    best, at = None, lo
    for a, b in spans:
        if a > at and (best is None or a - at > best[1] - best[0]):
            best = (at, a)
        at = max(at, b)
    if hi > at and (best is None or hi - at > best[1] - best[0]):
        best = (at, hi)
    if best is None or best[1] - best[0] < MIN_GUTTER_PX:
        return None
    return (best[0] + best[1]) / 2


def cut_regions(lines):
    """(regions, reason). `regions` is None when the page must stay whole.

    Each region: {"box": (x0, top, x1, bottom), "lines": [[word, ...]],
    "text": str, "identity": {...}} in reading order — rows top to bottom,
    left to right within a row.
    """
    anchors = find_anchors(lines)
    if len(anchors) < 2:
        return None, f"{len(anchors)} MICR band(s) on the page"
    ids = [a["identity"] for a in anchors if a["identity"]]
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if same_band(a, b) is not False:
                return None, ("two MICR bands on the page could be the same "
                              "cheque")
    words = [w for ln in lines for w in ln]
    rows = _rows(anchors)
    cells = []                       # (y_lo, y_hi, x_lo, x_hi, anchor)
    y_lo = float("-inf")
    for r, row in enumerate(rows):
        y_hi = (max(a["bottom"] for a in row) if r + 1 < len(rows)
                else float("inf"))
        band_words = [w for w in words
                      if y_lo < (float(w["top"]) + float(w["bottom"])) / 2 <= y_hi]
        cuts = [float("-inf")]
        for a, b in zip(row, row[1:]):
            g = _gutter(band_words, a["x1"], b["x0"])
            if g is None:
                return None, ("no empty gutter between two cheques side by "
                              "side")
            cuts.append(g)
        cuts.append(float("inf"))
        for k, a in enumerate(row):
            cells.append((y_lo, y_hi, cuts[k], cuts[k + 1], a))
        y_lo = max(a["bottom"] for a in row)

    regions = []
    for y0, y1, x0, x1, a in cells:
        def mine(w):
            cy = (float(w["top"]) + float(w["bottom"])) / 2
            cx = (float(w["x0"]) + float(w["x1"])) / 2
            return y0 < cy <= y1 and x0 < cx <= x1
        rl = [[w for w in ln if mine(w)] for ln in lines]
        rl = [ln for ln in rl if ln]
        n = sum(len(ln) for ln in rl)
        if n < MIN_REGION_WORDS:
            return None, f"a cheque region would hold only {n} word(s)"
        ws = [w for ln in rl for w in ln]
        regions.append({
            "box": (min(float(w["x0"]) for w in ws), min(float(w["top"]) for w in ws),
                    max(float(w["x1"]) for w in ws), max(float(w["bottom"]) for w in ws)),
            "lines": rl,
            "text": "\n".join(" ".join(str(w["text"]) for w in ln) for ln in rl),
            "identity": a["identity"]})
    if sum(len(ln) for r in regions for ln in r["lines"]) != len(words):
        return None, "some words on the page fall in no cheque region"
    return regions, ""
