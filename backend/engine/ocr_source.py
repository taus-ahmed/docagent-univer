# -*- coding: utf-8 -*-
"""An OCR reader behind the `read_page` seam — Tesseract, and nothing else.

`PageSource` (engine/text_layer.py, design docs/OCR-READER-SEAM-DESIGN.md) says
a reader supplies words with boxes, declares the space those boxes are in, and
declares WHAT IT CAN DO. This is that, for a page that has no text layer to
read: the page is rendered to an image, straightened, and handed to Tesseract.

WHAT THIS READER DECLARES, and why each one is a measurement rather than a hope
(shortlist evidence, this session):

    CHARACTER_GEOMETRY       NO. `image_to_data` is word-level. Tesseract can
                             emit character boxes, but not in the same pass, and
                             a raster has no font size to separate overprinted
                             texts by — the check would not mean what it means
                             on a digital page.
    SIZE_AWARE_TOKENISATION  NO. `shard_ratio` is a diff between a size-aware
                             and a size-blind tokenisation by ONE reader.
                             Tesseract segments the page once. A surrogate built
                             from that one segmentation is a diff against
                             itself, which measures nothing.
    TRUE_FONT_SIZE           NO. `WordFontAttributes` returns a point size only
                             under the LEGACY engine; with the LSTM engine
                             (the default since 4.0) it is unavailable.

So every capability-gated check SKIPS and the document records that it was not
performed — `unchecked_shred_pages`, `unchecked_overprint_pages` — which is the
whole point of the capability set: "this page is clean" and "this reader cannot
look" must not arrive as the same answer.

COORDINATES. Pixels, top-left origin, at the dpi the render was actually
performed at — never a remembered default. `normalise_words` converts once at
the seam, the same conversion `PixelSource` is tested through
(tests/test_reader_seam.py) and measured through (tests/harness/ocr_feasibility).

⚠ SYNTHETIC EVIDENCE ONLY. Everything measured about this reader was measured
on 54 synthetic cheque images and on gold pages rendered from their own vector
text. No client document has been through it.
"""
from __future__ import annotations

import re

from PIL import Image

from text_layer import CoordinateSpace, PageSource

#: The render the pipeline asks for. 300dpi is Tesseract's own documented
#: floor: "Tesseract works best on images which have a DPI of at least 300 dpi".
OCR_DPI = 300

#: Deskew search. Real scans skew by a few degrees; beyond this it is not a
#: skew, it is a page fed in sideways, which is ORIENTATION and is answered by
#: Tesseract's own OSD instead.
SKEW_LIMIT = 15.0
SKEW_COARSE = 1.0
SKEW_FINE = 0.1
#: Below this the page is NOT rotated, because rotating it reads WORSE.
#:
#: MEASURED, not assumed (tests/reports/ocr_checks_tesseract_seam*.json). On
#: the 18 moderate cheques — real skews of 1.0 to 4.9 degrees — correcting the
#: skew LOST 3 routing numbers, 3 account numbers and 5 amounts, turned one
#: numeral/words mismatch undecidable, and produced 5 wrong cheque numbers
#: where there had been none. On the 18 hard cheques — 6.0 to 14.0 degrees —
#: the same correction took the tier off zero for the first time. Tesseract's
#: own line finding absorbs a few degrees; resampling to fix what it already
#: tolerates only blurs the glyph edges it reads.
#:
#: ⚠ 6.0 is the boundary between two SYNTHETIC degradation tiers, fitted to
#: 36 images. It is not a property of real scanners, and the right value for a
#: client's scans can only be measured on a client's scans.
SKEW_MIN = 6.0
#: The projection profile is computed on a downscaled copy. Skew is a property
#: of where the text LINES are, not of the glyphs, so it survives downscaling —
#: and the search is ~40 rotations, which at full size would cost seconds.
SKEW_WIDTH = 800


#: Where a Tesseract binary is found when it is not on PATH. `TESSERACT_CMD`
#: wins, then PATH, then the Windows installer's own location — the Linux
#: image installs it on PATH, so that list is for development machines.
_WINDOWS_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _configure():
    """Point pytesseract at a binary it can actually run. Returns the module.

    ⚠ NOT a silent fallback: if none of these exist, the caller's own call
    raises and `_ocr_page` records the page as one that could not be read.
    """
    import os
    import shutil

    import pytesseract
    for candidate in (os.environ.get("TESSERACT_CMD"),
                      shutil.which("tesseract"), _WINDOWS_DEFAULT):
        if candidate and os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            break
    return pytesseract


def available():
    """(True, version) when a Tesseract binary can actually be called."""
    try:
        return True, str(_configure().get_tesseract_version())
    except Exception as exc:                      # pragma: no cover - env probe
        return False, f"{type(exc).__name__}: {exc}"


# ── straightening, as two separate steps ─────────────────────────────────────

def orientation(image):
    """0/90/180/270 — how far the page is turned, per Tesseract's own OSD.

    OSD ("orientation and script detection") is Tesseract's standard answer to
    this and is what `--psm 0` exists for. It is a CLASSIFIER over four
    right-angle orientations; it does not measure a two-degree skew, which is
    why deskew is a separate step below rather than an extension of this one.
    """
    try:
        osd = _configure().image_to_osd(image)
        m = re.search(r"Rotate: (\d+)", osd)
        return int(m.group(1)) % 360 if m else 0
    except Exception:
        # OSD needs its own trained data (osd.traineddata) and refuses pages
        # with too little text. Both are ordinary; neither is a reason to
        # guess an orientation.
        return 0


def _profile_variance(image, angle):
    """Variance of the horizontal projection profile at `angle`.

    THE PROJECTION PROFILE METHOD (Postl, 1986), the standard skew estimator:
    project the page onto the vertical axis at a range of candidate angles and
    take the angle whose profile varies most. Straight text lines put ink in
    some rows and none between them — peaks and troughs — while a skewed page
    smears ink across every row and flattens the profile.

    ⚠ NO NUMPY IN THIS ENVIRONMENT, and no OpenCV, so the projection is done
    with Pillow's own C resampling: resizing to a single column with the BOX
    filter averages each row, which IS the horizontal projection profile. The
    variance is then computed over a few hundred floats in Python.
    """
    # `image` arrives INVERTED — ink high, background 0 — so the corners a
    # rotation brings in must be filled with 0. Filling them with 255 fills
    # them with ink, and the variance then peaks at the most extreme angle in
    # the search band on EVERY page, skew or none.
    rot = image.rotate(angle, resample=Image.BILINEAR, expand=False,
                       fillcolor=0)
    rows = rot.resize((1, rot.height), Image.BOX).getdata()
    n = len(rows)
    if not n:
        return 0.0
    mean = sum(rows) / n
    return sum((v - mean) ** 2 for v in rows) / n


def skew_angle(image):
    """The page's skew in degrees (positive = anticlockwise correction), or 0.0.

    Coarse to fine: whole degrees across the search band, then a tenth of a
    degree around the winner. Reported, never applied here, so the caller can
    record what it did.
    """
    small = image.convert("L")
    if small.width > SKEW_WIDTH:
        h = max(1, int(small.height * SKEW_WIDTH / small.width))
        small = small.resize((SKEW_WIDTH, h), Image.BILINEAR)
    # Ink as high values: the profile should peak ON the text lines.
    small = small.point(lambda v: 255 - v)

    def best(angles):
        return max(angles, key=lambda a: _profile_variance(small, a))

    coarse = best([i * SKEW_COARSE
                   for i in range(int(-SKEW_LIMIT / SKEW_COARSE),
                                  int(SKEW_LIMIT / SKEW_COARSE) + 1)])
    fine = best([round(coarse + i * SKEW_FINE, 2) for i in range(-9, 10)])
    return 0.0 if abs(fine) < SKEW_MIN else fine


def straighten(image):
    """(image, {rotated, deskewed}) — orientation first, then skew.

    Two steps, in this order and never merged: OSD answers a page that was fed
    in sideways, the profile answers a page that was fed in crooked, and a page
    can be both. Each is reported separately so a later measurement can say
    which one earned its keep.
    """
    applied = {"rotated": 0, "deskewed": 0.0}
    turn = orientation(image)
    if turn:
        image = image.rotate(-turn, expand=True, fillcolor="white")
        applied["rotated"] = turn
    angle = skew_angle(image)
    if angle:
        image = image.rotate(angle, resample=Image.BICUBIC, expand=True,
                             fillcolor="white")
        applied["deskewed"] = angle
    return image, applied


# ── the reader ───────────────────────────────────────────────────────────────

class OcrPageSource(PageSource):
    """One rendered page, read by Tesseract, behind the seam.

    `straighten=False` reads the image exactly as given, which is how the
    deskew step is measured against itself rather than assumed to help.
    """

    #: Empty, and each absence is argued in the module docstring.
    capabilities = frozenset()

    def __init__(self, image, page_number=None, dpi=OCR_DPI, straighten_page=True):
        self._image = image
        self._page_number = page_number
        self._dpi = float(dpi)
        self.applied = {"rotated": 0, "deskewed": 0.0}
        if straighten_page:
            self._image, self.applied = straighten(self._image)
        self._data = None

    @property
    def page_number(self):
        return self._page_number

    @property
    def space(self):
        # The dpi is the one this page was RENDERED at, carried here rather
        # than remembered as a constant: a caller that renders at 200 and
        # declares 300 is the silent unit mismatch the declaration exists to
        # make impossible.
        return CoordinateSpace(unit="px", origin="top-left", dpi=self._dpi,
                               height=float(self._image.height),
                               width=float(self._image.width))

    def _read(self):
        if self._data is None:
            pytesseract = _configure()
            self._data = pytesseract.image_to_data(
                self._image, output_type=pytesseract.Output.DICT)
        return self._data

    def words(self, size_aware=True):
        # `size_aware` is IGNORED and the capability is NOT declared. Tesseract
        # segments the page once; answering as though a second, size-blind
        # reading existed would manufacture the very number the shredded-layer
        # check compares against.
        d = self._read()
        out = []
        for i, level in enumerate(d["level"]):
            text = (d["text"][i] or "").strip()
            if level != 5 or not text:
                continue
            x0, top = float(d["left"][i]), float(d["top"][i])
            out.append({"text": text, "x0": x0, "x1": x0 + float(d["width"][i]),
                        "top": top, "bottom": top + float(d["height"][i]),
                        "conf": float(d["conf"][i])})
        return out

    def raw_text(self):
        """The page as lines, rebuilt from the SAME pass the words come from.

        Not a second `image_to_string` call: two passes can disagree, and the
        text is what grounding checks a quoted span against, so it must be the
        text these words spell.
        """
        d = self._read()
        lines, order = {}, []
        for i, level in enumerate(d["level"]):
            text = (d["text"][i] or "").strip()
            if level != 5 or not text:
                continue
            key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            if key not in lines:
                lines[key] = []
                order.append(key)
            lines[key].append(text)
        return "\n".join(" ".join(lines[k]) for k in order)

    def chars(self):
        # No CHARACTER_GEOMETRY: the seam must not call this, and if it does,
        # an empty list is the truthful answer rather than a guess.
        return []


def render_pdf_page(path, page_number, dpi=OCR_DPI):
    """One PDF page as an image, or None. `page_number` is 1-based."""
    try:
        from pdf2image import convert_from_path
        pages = convert_from_path(str(path), dpi=dpi,
                                  first_page=page_number, last_page=page_number)
        return pages[0] if pages else None
    except Exception:
        return None
