"""The MICR band read as its own check (Run S, Stage 4c).

A page reading treats the MICR band like any other line, and a general OCR
model reads its digits in a font made for magnetic readers: on the
synthetic set the plain reading turned `0` into `@` (`A@25435304A`), and no
band was found at all. The band has a closed alphabet - ten digits and four
sentinels - and a fixed place (the bottom of the cheque), so it is read on
its own:

  1. LOCATE: the lowest line of the page reading whose characters are mostly
     digits (9 or more), else the bottom fifth of the image;
  2. READ: that strip, cropped with a margin, scaled 2x, read as ONE line with
     the alphabet restricted to digits and the ASCII sentinel stand-ins the
     parser accepts (micr.py: A/T transit, C on-us, B amount, D dash);
  3. PARSE: micr.parse_micr - structure first, and a routing number only
     when it passes the ABA checksum.

The result is evidence of its own: `check_against(fields, band)` compares
routing, account and cheque number answered by anyone (the model, the page
reading) with the band, and names every disagreement.

What this cannot do: a real E-13B face is not in Tesseract's training data,
and the synthetic set prints the band in a monospace stand-in. Real cheques
are NOT verified (docs/RUN_S_REPORT.md).
"""
from __future__ import annotations

import re

ALPHABET = "0123456789ATCBD"
CONFIG = f"--psm 7 -c tessedit_char_whitelist={ALPHABET}"


def _digit_share(text):
    t = re.sub(r"\s", "", str(text or ""))
    return (sum(ch.isdigit() for ch in t) / len(t)) if t else 0.0


def locate(words, image_height):
    """(top, bottom) of the MICR strip in image pixels, from a page reading's
    words (dicts with text/top/bottom/line_id), or the bottom fifth."""
    lines = {}
    for w in words or ():
        lines.setdefault(w.get("line_id", round(float(w["top"]) / 12)), []).append(w)
    best = None
    for ws in lines.values():
        text = " ".join(w["text"] for w in ws)
        if sum(ch.isdigit() for ch in text) >= 9 and _digit_share(text) >= 0.6:
            top = min(float(w["top"]) for w in ws)
            bot = max(float(w["bottom"]) for w in ws)
            if top > 0.5 * image_height and (best is None or top > best[0]):
                best = (top, bot)
    if best:
        pad = (best[1] - best[0]) * 0.6
        return max(0, best[0] - pad), min(image_height, best[1] + pad)
    return 0.8 * image_height, float(image_height)


_BETWEEN = re.compile(r"(?<=\d)[OoQDlI|iSZBg](?=\d)")
_MAP = {"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "|": "1", "i": "1",
        "S": "5", "Z": "2", "B": "8", "g": "9"}


def demangle(text) -> str:
    """Confusable glyphs a general OCR model reads in a MICR band, repaired
    INSIDE the band only: `@` is always a zero there; a letter between two
    digits is the digit it looks like. Sentinel stand-ins between fields
    (A, T, C, B, D next to a space or an end) are left alone."""
    t = str(text or "").replace("@", "0")
    prev = None
    while prev != t:
        prev, t = t, _BETWEEN.sub(lambda m: _MAP.get(m.group(0), m.group(0)), t)
    return t


def _ocr(image, config=""):
    from ocr_source import _configure
    import external_tools
    pytesseract = _configure()
    text = external_tools.tesseract(pytesseract.image_to_string, image, config=config)
    return re.sub(r"\s+", " ", str(text or "")).strip()


def readings(image, words=None):
    """Candidate band texts, most direct first: the page reading's own band
    line, the strip read freely, the strip read in the band's alphabet. Each
    repaired by `demangle`."""
    out = []
    lines = {}
    for w in words or ():
        lines.setdefault(w.get("line_id", round(float(w["top"]) / 12)), []).append(w)
    top, bot = locate(words, image.height)
    for ws in lines.values():
        if min(float(w["top"]) for w in ws) >= top - 2 and \
                max(float(w["bottom"]) for w in ws) <= bot + 2:
            out.append(" ".join(w["text"] for w in sorted(ws, key=lambda w: w["x0"])))
    strip = image.convert("L").crop((0, int(top), image.width, int(bot)))
    strip = strip.resize((strip.width * 2, max(1, strip.height * 2)))
    out.append(_ocr(strip, "--psm 7"))
    out.append(_ocr(strip, CONFIG))
    return [demangle(t) for t in out if t]


def read_band(image, words=None):
    """The MICR band's text read from `image` (a PIL image), or ''. The first
    reading whose transit field passes the ABA checksum wins; failing that,
    the reading the parser gets the most fields from."""
    cands = readings(image, words)
    best, score = "", -1
    for t in cands:
        got = parse(t)
        if got.get("routing_number"):
            return t
        if len(got) > score:
            best, score = t, len(got)
    return best


def parse(band_text) -> dict:
    import micr
    return micr.parse_micr(band_text) if band_text else {}


_ROLE = {"routing_number": "routing", "account_number": "account",
         "serial_number": "cheque number"}


def check_against(fields: dict, band: dict) -> list:
    """[(role, answered, band value)] for every field the answer and the band
    both hold and that differ (digits compared, separators aside)."""
    out = []
    for key, role in _ROLE.items():
        a = re.sub(r"\D", "", str(fields.get(key) or ""))
        b = re.sub(r"\D", "", str(band.get(key) or ""))
        if a and b and a.lstrip("0") != b.lstrip("0"):
            out.append((role, fields.get(key), band.get(key)))
    return out
