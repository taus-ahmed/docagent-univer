"""Run S, after Stage 4: the MICR band must read the same on every OCR build.

CI (GitHub's Ubuntu runner, Tesseract 5.3) and the production image (Railway,
Linux, Tesseract 5.3) read the generated scan batch's page 8 band as
`AG06474687A ...`: the routing number's leading 6 read as `G`
(tests/harness/tesseract_gate.py, measured 2026-10-28). Windows' Tesseract 5.4
reads the 6. A letter at the EDGE of the transit field is not "between two
digits", so `demangle` left it, the band did not parse, no new-cheque boundary
was found, and pages 7 and 8 came back as one record on Linux only.

The rule made reader-independent here: inside the transit field (nine
characters between two transit sentinels), ONE glyph a general OCR model
confuses with digits is resolved by the ABA checksum: among the digits that
glyph can be, the one the checksum accepts is kept, and only when exactly one
is. More than one non-digit, or a glyph with no digit look-alike, or no
candidate passing, leaves the band as read.

The first test reproduces the Linux reading itself, so the difference between
the two readers is visible on a Windows run too. Invented band values except
the generated fixture's own page-8 routing number.
"""
from __future__ import annotations

import pytest

import micr
import micr_reader as MR

LINUX_PAGE_8 = "AG06474687A 723430980500C"   # 5.3's reading; 5.4 reads A606474687A
TRUTH_ROUTING = "606474687"


def test_the_linux_reading_of_page_8_did_not_parse_before_the_repair():
    """The difference itself: 5.4's band parses, 5.3's does not."""
    assert micr.parse_micr("A606474687A 723430980500C").get("routing_number") == TRUTH_ROUTING
    assert not micr.parse_micr(LINUX_PAGE_8).get("routing_number")
    assert not micr.parse_micr(MR.demangle(LINUX_PAGE_8)).get("routing_number")


def test_the_linux_reading_of_page_8_repairs_to_the_same_routing_number():
    fixed = MR.repair_transit(MR.demangle(LINUX_PAGE_8))
    assert micr.parse_micr(fixed).get("routing_number") == TRUTH_ROUTING
    assert fixed.split()[1:] == LINUX_PAGE_8.split()[1:]      # nothing else touched


@pytest.mark.parametrize("band", [
    "A606474687A 723430980500C",      # already valid: unchanged
])
def test_a_valid_band_is_left_as_read(band):
    assert MR.repair_transit(band) == band


@pytest.mark.parametrize("band", [
    "AG0G474687A 723430980500C",      # two unknown glyphs: no single answer
    "AX06474687A 723430980500C",      # X looks like no digit
    "A60647468GA 723430980500C",      # G's look-alikes (6, 0, 9): none passes here
    "AG064746A 723430980500C",        # not nine characters
])
def test_an_unresolvable_transit_field_is_left_as_read(band):
    assert MR.repair_transit(band) == band
    assert not micr.parse_micr(MR.repair_transit(band)).get("routing_number")


def test_the_repair_runs_inside_the_page_reading(monkeypatch):
    """`OcrPageSource._repair_micr_band` uses it: a reading whose lowest
    digit line is the Linux page-8 band comes out with the valid band."""
    from PIL import Image
    from ocr_source import OcrPageSource
    img = Image.new("RGB", (1200, 600), "white")
    s = OcrPageSource(img, dpi=300)
    words = ["PAY", "TO", "THE", "ORDER", "OF", *LINUX_PAGE_8.split()]
    tops = [100] * 5 + [500] * 2
    s._data = {"level": [5] * len(words), "text": list(words),
               "conf": ["90"] * len(words), "top": tops,
               "left": [40 + 120 * i for i in range(len(words))],
               "width": [100] * len(words), "height": [20] * len(words),
               "block_num": [1] * len(words), "par_num": [1] * len(words),
               "line_num": [1 if t == 100 else 2 for t in tops],
               "word_num": list(range(len(words))), "page_num": [1] * len(words)}
    s.applied = {}
    s._repair_micr_band()
    band = " ".join(t for t, top in zip(s._data["text"], tops) if top == 500)
    assert micr.parse_micr(band).get("routing_number") == TRUTH_ROUTING
    assert s.applied["micr_band"] == "repaired"
