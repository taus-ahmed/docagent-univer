"""OCR lines are the reader's lines — Gate 2b, phase 1 (RED, no fix yet).

A scan skewed by a few degrees is not deskewed (`ocr_source.SKEW_MIN`, whose
measurement says correcting 1-5 degrees reads WORSE). Tesseract's own line
finding absorbs that skew, and `raw_text` — the text the model is prompted
with and grounding checks against — comes back as whole lines. But the
GEOMETRY was regrouped from the word boxes by vertical distance
(`group_lines`, LINE_TOL = 3pt), and a line climbing ~8pt across a cheque is
three or four "lines" to that rule, in the wrong order:

    Tesseract:  PAY TO THE ORDER OF: John A. Smith
    geometry:   [A. Smith] [ORDER OF: John] [PAY TO THE]

So the text and the geometry describe two different pages, and every
consumer of geometry fails on a TRUE value: D9 (`matches_loosely`) flagged
21.9% of the values Tesseract read correctly across the generated variants
(measured with the gate2-aborted stash harness; re-measured for Gate 2b).

Also here: the deskew estimator on a page with no ink. The projection
profile is flat at every angle, and the search returned the edge of its band
(-15.9 degrees) instead of "no skew measured".

And the hard-tier scan `scan_hard_single`, on which Tesseract reads ZERO
words: a cheque skewed ~14 degrees on a shaded page. The skew estimator
projects GREY pixels, so the shaded background outweighs the thin text and
0 degrees wins; even straightened, psm 3 finds no text block on the mostly
blank letter page. Gate 2 already names the zero-word page (guard below);
the known_bug test asks for a real reading.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from PIL import Image

from tests.harness import bootstrap as bs

bs.bootstrap()

import ocr_source  # noqa: E402
from ocr_source import OCR_DPI, OcrPageSource, available, render_pdf_page  # noqa: E402
from text_layer import matches_loosely, read_page  # noqa: E402

HAS_TESSERACT, TESSERACT_VERSION = available()
needs_tesseract = pytest.mark.skipif(
    not HAS_TESSERACT, reason=f"no tesseract binary: {TESSERACT_VERSION}")

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
FIELDS = ("bank", "payee", "check_number", "date", "amount_numeral",
          "amount_words_shown", "routing_number", "account_number", "memo")
#: Generated variants whose scanned pages are moderate-tier: 1-5 degrees.
SKEWED = ["scan_only_single", "scan_two_and_three_up"]


@pytest.fixture(scope="module")
def variants(tmp_path_factory):
    out = tmp_path_factory.mktemp("scan_variants_geometry")
    proc = subprocess.run([sys.executable, str(GENERATOR), "--out", str(out),
                           "--repo", str(bs.REPO_DIR), "--verify"],
                          capture_output=True)
    said = (proc.stdout.decode("utf-8", "replace")
            + proc.stderr.decode("utf-8", "replace"))
    assert proc.returncode == 0 and "verify: ok" in said, said
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    return out, {v["file"][:-len(".pdf")]: v for v in manifest["variants"]}


_READ: dict = {}


def _read(variants, name, page):
    """(source, raw text, engine lines) — the production path, once per page."""
    key = (name, page)
    if key not in _READ:
        image = render_pdf_page(variants[0] / f"{name}.pdf", page, dpi=OCR_DPI)
        src = OcrPageSource(image, page_number=page, dpi=OCR_DPI)
        raw = src.raw_text()
        _t, lines, _r = read_page(src, stats={})
        _READ[key] = (src, image, raw, lines)
    return _READ[key]


def _reader_lines(raw):
    return [[{"text": t} for t in ln.split()] for ln in raw.split("\n")
            if ln.strip()]


def _scan_pages(variants, name):
    return [p for p in variants[1][name]["pages"] if p["origin"] == "scan"]


@needs_tesseract
class TestThePagesReallyAreSkewed:
    """Unmarked precondition. If a page were straight, the red tests below
    would be red for some other reason."""

    @pytest.mark.parametrize("name", SKEWED)
    def test_each_scanned_page_is_skewed_between_1_and_5_degrees(
            self, variants, name):
        for p in _scan_pages(variants, name):
            _src, image, _raw, _lines = _read(variants, name, p["page"])
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(ocr_source, "SKEW_MIN", 0.0)
                angle = ocr_source.skew_angle(image)
            assert 1.0 <= abs(angle) <= 5.0, (name, p["page"], angle)


@needs_tesseract
class TestOcrLinesAreTheReadersLines:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "group_lines regroups OCR word boxes by vertical distance (LINE_TOL), "
        "so a line sloping a few degrees becomes fragments out of order"))
    @pytest.mark.parametrize("name", SKEWED)
    def test_geometry_lines_spell_the_readers_lines_in_order(self, variants, name):
        """Red at 838f0a7: group_lines regrouped OCR word boxes by vertical
        distance, so a sloping line became several fragments out of order."""
        for p in _scan_pages(variants, name):
            _src, _img, raw, lines = _read(variants, name, p["page"])
            geo = [" ".join(w["text"] for w in ln) for ln in lines]
            assert geo == [ln.strip() for ln in raw.split("\n") if ln.strip()]

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "D9 (matches_loosely) runs over the fragmented geometry and flags "
        "values Tesseract read correctly"))
    @pytest.mark.parametrize("name", SKEWED)
    def test_a_value_ocr_read_correctly_passes_the_geometry_check(
            self, variants, name):
        """Red at 838f0a7: D9 (matches_loosely) ran over the fragmented
        geometry and flagged values Tesseract had read correctly."""
        flagged, read = [], 0
        for p in _scan_pages(variants, name):
            _src, _img, raw, lines = _read(variants, name, p["page"])
            rl = _reader_lines(raw)
            for c in p["cheques"]:
                for f in FIELDS:
                    val = str(c["fields"].get(f) or "").strip()
                    if val and matches_loosely(val, rl):
                        read += 1
                        if not matches_loosely(val, lines):
                            flagged.append((p["page"], c["id"], f, val))
        assert read > 0
        assert flagged == []


class TestABlankPageHasNoSkew:

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "a flat projection profile ties at every angle and max() returns "
        "the edge of the search band, -15.9 degrees"))
    def test_a_page_with_no_ink_measures_zero(self):
        """Red at 838f0a7 (-15.9): the projection profile is flat at every
        angle on a blank page, and the search returned the edge of its band."""
        blank = Image.new("L", (2550, 3300), 255)
        assert ocr_source.skew_angle(blank) == 0.0


@needs_tesseract
class TestTheHardScan:
    """`scan_hard_single`: one hard-tier cheque (6-14 degrees, blur, shading)."""

    def test_a_zero_word_reading_is_named_never_silent(self, variants):
        """GUARD, unmarked (Gate 2 already holds it): whatever OCR manages,
        a page it reads nothing from is listed and named, never a success."""
        from core.preprocessor import preprocess_file
        doc = preprocess_file(variants[0] / "scan_hard_single.pdf")
        words = sum(len(ln) for ln in doc.page_lines[0])
        assert doc.ocr_pages and doc.ocr_pages[0]["words"] == words
        if words == 0:
            assert doc.ocr_zero_word_pages == [1]
            assert "page 1" in doc.processing_notes

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "Tesseract reads 0 words: the grey-profile skew estimator returns 0 "
        "on a shaded page, and psm 3 finds no text block on the mostly blank "
        "page. Measured: ink-only deskew + crop to ink + psm 6 reads 4 of 9 "
        "true fields"))
    def test_the_hard_scan_is_actually_read(self, variants):
        _src, _img, raw, _lines = _read(variants, "scan_hard_single", 1)
        rl = _reader_lines(raw)
        fields = variants[1]["scan_hard_single"]["pages"][0]["cheques"][0]["fields"]
        read = [f for f in FIELDS if str(fields.get(f) or "").strip()
                and matches_loosely(str(fields[f]), rl)]
        assert len(read) >= 3, (read, raw[:200])
