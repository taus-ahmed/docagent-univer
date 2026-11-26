"""Watermark and background suppression before OCR (Run S, Stage 4b).

A cheque's face is printed over things that are not its text: a tiled
"ORIGINAL DOCUMENT" word, a diagonal security text, a guilloche line
pattern, a VOID/SAMPLE overprint, a phone photo's shadow. Tesseract reads
some of it as words and loses real words under it. Each cleanup below is one
idea, measurable on its own (tools/eval_synthetic_checks.py); which one the
reader uses is chosen by measured accuracy on the synthetic set, not by
taste - see `DEFAULT` and docs/RUN_S_REPORT.md.

  none        the image as given (the reader's own binarisation)
  ink         COLOUR: keep pixels that are dark AND unsaturated (printed
              ink); a saturated overprint (red VOID) and a pale pattern
              (blue guilloche, grey tiled text) go to white
  otsu        THRESHOLD: grey, flattened against its own blurred background
              (removes a shadow), then cut at Otsu's threshold
  median      FREQUENCY: the `ink` image with a 3x3 median filter, which
              erases one-pixel pattern lines and speckle but not strokes
  ink_x15     MULTI-SCALE: `ink` read at 1.5x
  unboxed     LINES: the `otsu` image with every long straight horizontal
              or vertical run of ink (a rule line, a box border) erased; a
              value printed inside a box or on a rule is read alone
  auto        the reader's default: `none`, and `otsu` only when the first
              reading is unsure; the more confident reading is kept
  multipass   MULTI-PASS: `none`, `otsu` and `unboxed` read separately;
              for every place on the page the LINE with the highest
              confidence is kept whole (a word-level merge was measured
              first and stitched values from two readings: 70.1%)

Pure PIL. Every function takes and returns a PIL image (RGB or L).
"""
from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps

VARIANTS = ("none", "ink", "otsu", "median", "ink_x15", "unboxed", "multipass", "auto")
#: the single-pass readings `multipass` combines (the measured best singles)
MULTIPASS = ("none", "otsu", "unboxed")
#: the variant the OCR reader applies (Stage 4b). Measured on the synthetic
#: set alone, `otsu` read most (83.7% against 80.2% for none); applied to every
#: page it cost the real rendered scans of the test suite strokes (5 tests: a
#: cheque's bottom line 11 words where 16+ are printed). `auto` keeps the page
#: as given unless that reading is unsure, then keeps the more confident of the
#: two readings - see ocr_source.OcrPageSource._read and docs/RUN_S_REPORT.md.
DEFAULT = "auto"
#: the cleanup `auto` tries, and the confidence under which it tries it
AUTO_VARIANT = "otsu"
AUTO_MIN = 85.0


def reading_score(data) -> float:
    """Character-weighted mean Tesseract confidence of one image_to_data
    reading (words only; unreadable boxes, conf -1, ignored). 0 when empty."""
    num = den = 0.0
    for i, level in enumerate(data.get("level") or []):
        t = (data["text"][i] or "").strip()
        try:
            c = float(data["conf"][i])
        except (TypeError, ValueError):
            continue
        if level == 5 and t and c >= 0:
            num += c * len(t)
            den += len(t)
    return num / den if den else 0.0


def _otsu(grey) -> int:
    hist = grey.histogram()[:256]
    total = sum(hist)
    s_all = sum(i * h for i, h in enumerate(hist))
    w_b = s_b = 0
    best, cut = -1.0, 128
    for t in range(256):
        w_b += hist[t]
        if not w_b:
            continue
        w_f = total - w_b
        if not w_f:
            break
        s_b += t * hist[t]
        m_b, m_f = s_b / w_b, (s_all - s_b) / w_f
        between = w_b * w_f * (m_b - m_f) ** 2
        if between > best:
            best, cut = between, t
    return cut


def ink(img, dark=110, chroma=60):
    """Dark, unsaturated pixels stay black; everything else goes white.

    Colourfulness is CHROMA (max channel - min channel), not HSV saturation:
    HSV divides by the brightest channel, so near-black ink (20, 20, 30)
    reads as 'saturated' and was thrown away (found by its own test)."""
    from PIL import ImageChops
    r, g, b = img.convert("RGB").split()
    hi = ImageChops.lighter(r, ImageChops.lighter(g, b))
    lo = ImageChops.darker(r, ImageChops.darker(g, b))
    c = ImageChops.subtract(hi, lo)
    keep_v = hi.point(lambda x: 255 if x <= dark else 0)
    keep_s = c.point(lambda x: 255 if x <= chroma else 0)
    mask = ImageChops.multiply(keep_v, keep_s)        # both true
    return ImageOps.invert(mask).convert("L")


def otsu(img):
    grey = img.convert("L")
    bg = grey.filter(ImageFilter.GaussianBlur(25))
    from PIL import ImageChops
    flat = ImageChops.subtract(bg, grey)             # ink is darker than its surround
    flat = ImageOps.invert(ImageOps.autocontrast(flat))
    cut = _otsu(flat)
    return flat.point(lambda x: 0 if x < cut else 255)


def median(img):
    return ink(img).filter(ImageFilter.MedianFilter(3))


def unboxed(img, run=None):
    """`otsu`, then every horizontal or vertical run of ink longer than
    `run` pixels (default 6% of the image's width) is turned white: rules and
    box borders, never a letter's stroke."""
    b = otsu(img)
    w, h = b.size
    run = int(run or max(40, 0.06 * w))
    px = b.load()
    erase = []
    for y in range(h):
        x = 0
        while x < w:
            if px[x, y] == 0:
                x0 = x
                while x < w and px[x, y] == 0:
                    x += 1
                if x - x0 >= run:
                    erase.append((x0, y, x, y + 1))
            else:
                x += 1
    for x in range(w):
        y = 0
        while y < h:
            if px[x, y] == 0:
                y0 = y
                while y < h and px[x, y] == 0:
                    y += 1
                if y - y0 >= max(run // 2, 25):
                    erase.append((x, y0, x + 1, y))
            else:
                y += 1
    from PIL import ImageDraw
    d = ImageDraw.Draw(b)
    for x0, y0, x1, y1 in erase:
        d.rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
    return b


def scaled(img, f):
    return img.resize((int(img.width * f), int(img.height * f)), Image.LANCZOS)


def apply(img, variant):
    """The cleaned image for one single-pass variant, and its scale factor
    relative to `img` (word boxes read from it are divided by the factor)."""
    if variant == "none":
        return img, 1.0
    if variant == "ink":
        return ink(img), 1.0
    if variant == "otsu":
        return otsu(img), 1.0
    if variant == "median":
        return median(img), 1.0
    if variant == "ink_x15":
        return scaled(ink(img), 1.5), 1.5
    if variant == "unboxed":
        return unboxed(img), 1.0
    raise ValueError(variant)


def _overlap(a, b) -> bool:
    w = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    h = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    if w <= 0 or h <= 0:
        return False
    area = min((a["x1"] - a["x0"]) * (a["bottom"] - a["top"]),
               (b["x1"] - b["x0"]) * (b["bottom"] - b["top"])) or 1.0
    return w * h >= 0.5 * area


def _lines(words, tag):
    by = {}
    for w in words:
        by.setdefault(w.get("line_id", round(float(w["top"]) / 12)), []).append(w)
    out = []
    for ws in by.values():
        conf = [float(w.get("conf", 0) or 0) for w in ws]
        chars = [len(str(w.get("text", ""))) for w in ws]
        out.append({"words": ws, "tag": tag,
                    "x0": min(w["x0"] for w in ws), "x1": max(w["x1"] for w in ws),
                    "top": min(w["top"] for w in ws), "bottom": max(w["bottom"] for w in ws),
                    "score": sum(c * n for c, n in zip(conf, chars)) / max(1, sum(chars))})
    return out


def merge_readings(readings):
    """MULTI-PASS: [[word]] from several readings of ONE page (same space) ->
    one word list. The unit is a LINE, not a word: where lines of different
    readings cover the same place, the line with the higher character-
    weighted Tesseract confidence is kept whole (a value is never stitched
    from two readings). Word line ids are renumbered per kept line."""
    pool = [ln for k, r in enumerate(readings) for ln in _lines(r, k)]
    pool.sort(key=lambda ln: -ln["score"])
    kept = []
    for ln in pool:
        if any(_overlap(ln, k) for k in kept):
            continue
        kept.append(ln)
    kept.sort(key=lambda ln: (ln["top"], ln["x0"]))
    out = []
    for i, ln in enumerate(kept):
        for w in sorted(ln["words"], key=lambda w: w["x0"]):
            w = dict(w)
            w["line_id"] = i
            out.append(w)
    return out
