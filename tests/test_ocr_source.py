# -*- coding: utf-8 -*-
"""The OCR reader behind the seam, and the page that routes to it.

Two things are pinned here, and they are different kinds of claim:

  STRUCTURAL — what the reader DECLARES (no capabilities, pixels at the dpi it
  was rendered at, top-left origin) and what the seam therefore does with it
  (skip both gated checks and record that they were skipped). These hold
  whatever Tesseract returns.

  BEHAVIOURAL — that a PDF with no text layer comes back with words, and that a
  PDF with one is not touched. These need the binary, and skip without it
  rather than passing quietly.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from PIL import Image  # noqa: E402

from ocr_source import (  # noqa: E402
    OCR_DPI, SKEW_MIN, OcrPageSource, available, skew_angle, straighten,
)
from text_layer import Capability, read_page  # noqa: E402

CORPUS = bs.TESTS_DIR / "test_OCR"
HAS_TESSERACT, TESSERACT_VERSION = available()
needs_tesseract = pytest.mark.skipif(
    not HAS_TESSERACT, reason=f"no tesseract binary: {TESSERACT_VERSION}")


@pytest.fixture(scope="module")
def clean_image():
    return Image.open(CORPUS / "chk_003_clean.png")


@pytest.fixture(scope="module")
def hard_image():
    return Image.open(CORPUS / "chk_003_hard.jpg")


class TestWhatTheReaderDeclares:
    """A capability is a claim about the READER. Declaring one Tesseract does
    not have would make a check that never ran look like a check that passed."""

    def test_it_declares_no_capabilities_at_all(self, clean_image):
        src = OcrPageSource(clean_image, straighten_page=False)
        assert src.capabilities == frozenset()
        for cap in (Capability.CHARACTER_GEOMETRY,
                    Capability.SIZE_AWARE_TOKENISATION,
                    Capability.TRUE_FONT_SIZE):
            assert not src.can(cap)

    def test_character_geometry_is_absent_not_empty_looking(self, clean_image):
        """`chars()` returning [] is only safe BECAUSE the capability is not
        declared: the seam never calls it, so no overprint check reads an empty
        page as a clean one."""
        assert OcrPageSource(clean_image, straighten_page=False).chars() == []

    def test_the_space_carries_the_dpi_it_was_rendered_at(self, clean_image):
        src = OcrPageSource(clean_image, dpi=200, straighten_page=False)
        space = src.space
        assert (space.unit, space.origin, space.dpi) == ("px", "top-left", 200)
        assert space.height == clean_image.height
        space.validate()               # refuses px without a dpi; this has one

    def test_the_default_render_is_tesseracts_documented_floor(self):
        assert OCR_DPI == 300


@needs_tesseract
class TestTheSeamSkipsBothGatedChecksAndSaysSo:
    def test_read_page_records_both_checks_as_not_performed(self, clean_image):
        stats = {}
        text, lines, _repairs = read_page(
            OcrPageSource(clean_image, page_number=1, straighten_page=False),
            stats=stats)
        assert stats.get("shard_checked") is False
        assert stats.get("overprint_checked") is False
        # ...and NOT a clean-looking ratio, which is what the gate exists for.
        assert "shard_ratio" not in stats
        assert text.strip() and lines

    def test_words_carry_the_contract_keys_and_land_in_points(self, clean_image):
        """After the seam converts, a word's box is in POINTS — so a cheque
        1800px wide at 300dpi is 432pt wide, not 1800 of anything."""
        _text, lines, _ = read_page(
            OcrPageSource(clean_image, page_number=1, straighten_page=False))
        words = [w for ln in lines for w in ln]
        assert words
        for w in words:
            assert {"text", "x0", "x1", "top", "bottom"} <= set(w)
        assert max(w["x1"] for w in words) <= clean_image.width * 72 / OCR_DPI + 1
        assert all(w["page"] == 1 for w in words)


class TestStraightening:
    """Deskew is its own step so it can be measured against itself, and it is
    deliberately NOT applied to a page whose skew Tesseract already tolerates."""

    def test_a_straight_page_is_measured_as_straight(self, clean_image):
        assert skew_angle(clean_image) == 0.0

    def test_a_crooked_page_is_measured_as_crooked(self, hard_image):
        angle = skew_angle(hard_image)
        assert abs(angle) >= SKEW_MIN
        assert abs(angle) <= 15.0

    def test_a_straight_page_is_left_alone(self, clean_image):
        out, applied = straighten(clean_image)
        assert applied["deskewed"] == 0.0
        assert out.size == clean_image.size

    def test_the_minimum_angle_is_the_measured_one(self):
        """Correcting 1-5 degrees measurably made recognition WORSE (see the
        constant's own note). If this is lowered, re-run
        `python -m tests.harness.ocr_checks --reader seam` and move the
        evidence with it."""
        assert SKEW_MIN == 6.0


@needs_tesseract
class TestAPageWithNoTextLayerIsRead(object):
    def test_a_textless_pdf_comes_back_with_words_and_says_it_was_ocrd(
            self, tmp_path):
        """The whole point: before this, such a page produced NOTHING, and the
        only sign was an empty prompt."""
        from core.preprocessor import preprocess_file
        pdf = tmp_path / "scan.pdf"
        Image.open(CORPUS / "chk_003_clean.png").convert("RGB").save(pdf)

        doc = preprocess_file(pdf)
        assert doc.ocr_pages and doc.ocr_pages[0]["page"] == 1
        assert doc.ocr_failed_pages == []
        assert "MILLBROOK" in doc.page_texts[0].upper()
        assert doc.page_lines[0], "geometry, not just characters"
        # The document is still typed as a scan, so slot extraction floors its
        # confidences to UNVERIFIED: OCR gives the model something to read, it
        # does not make a machine's reading the document's own words.
        assert doc.native_text_chars == 0
        assert doc.has_meaningful_text is False

    def test_a_digital_pdf_is_not_ocrd_at_all(self):
        """Every gold PDF has a text layer on every page. If this ever fires,
        the routing rule has widened and the accuracy harness is measuring a
        different reader than it thinks."""
        from core.preprocessor import preprocess_file
        doc = preprocess_file(bs.PDF_DIR / "CHQ-001847.pdf")
        assert doc.ocr_pages == []
        assert doc.ocr_failed_pages == []
        assert doc.has_meaningful_text is True
