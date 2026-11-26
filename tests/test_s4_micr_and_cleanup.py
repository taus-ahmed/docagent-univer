"""Run S, Stage 4 — the MICR band read as its own check (4c), watermark and
background cleanup (4b), and the band against the answer (4d).

Unit tests need nothing; the image tests need Tesseract and skip without it.
The synthetic check images are generated in the test by
tools/make_synthetic_checks.py, so they run on CI too.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import image_cleanup as IC  # noqa: E402
import micr_reader as MR  # noqa: E402


def _tesseract():
    try:
        import ocr_source
        ok, why = ocr_source.available()
        if not ok:
            pytest.skip(f"Tesseract not installed: {why}")
    except Exception as e:                       # noqa: BLE001
        pytest.skip(f"OCR reader unavailable: {e}")


# ── 4c: the band ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,fixed", [
    ("A@25435304A 638274058C 1976", "A025435304A 638274058C 1976"),
    ("A0254353O4A 6382l4058C 1976", "A025435304A 638214058C 1976"),
    ("A025435304A 638274058C 1976", "A025435304A 638274058C 1976"),
])
def test_demangle_repairs_confusables_inside_the_band_only(raw, fixed):
    assert MR.demangle(raw) == fixed


def test_demangle_leaves_sentinels_between_fields():
    assert MR.demangle("C001002C A423511613A 559407816184C") == \
        "C001002C A423511613A 559407816184C"


def test_locate_finds_the_lowest_digit_line():
    words = [{"text": "PAY", "top": 200, "bottom": 220, "line_id": 1},
             {"text": "A025435304A", "top": 560, "bottom": 590, "line_id": 9},
             {"text": "638274058C", "top": 560, "bottom": 590, "line_id": 9}]
    top, bot = MR.locate(words, 660)
    assert top < 560 and bot > 590


def test_check_against_names_each_disagreement():
    band = {"routing_number": "025435304", "account_number": "638274058",
            "serial_number": "1976"}
    got = MR.check_against({"routing_number": "025435304", "account_number": "638274O58",
                            "serial_number": "1979"}, band)
    roles = {r for r, _a, _b in got}
    assert roles == {"account", "cheque number"}
    assert MR.check_against({"routing_number": "25435304"}, band) == []


def _check_image(i, **over):
    import make_synthetic_checks as G
    rng = random.Random(77 + i)
    t = G.make_truth(i, rng)
    t.update(over)
    img = G.capture(G.draw_check(t, rng), t, rng)
    return t, img


def test_the_band_reader_reads_a_clean_check():
    _tesseract()
    t, img = _check_image(0, watermark="none", capture="scan")
    import eval_synthetic_checks as E
    words = E.read(img, "none")
    got = MR.parse(MR.read_band(img, words))
    assert got.get("routing_number") == t["fields"]["routing"]
    assert got.get("account_number") == t["fields"]["account"]


def test_the_ocr_page_repairs_its_band_words_in_place():
    """Perception: an OCR page's MICR line is repaired word by word (boxes
    kept) when, and only when, the repair makes the band parse with a
    checksum-valid routing number - so grounding, the MICR fill and the
    cheque validators all see the band as printed."""
    _tesseract()
    from ocr_source import OcrPageSource
    import micr
    t, img = _check_image(0, watermark="none", capture="scan")
    src = OcrPageSource(img, dpi=200)
    band = micr.find_micr_line(src.raw_text())
    assert micr.parse_micr(band).get("routing_number") == t["fields"]["routing"]
    assert src.applied.get("micr_band") in ("repaired", "as_read", "reread")
    assert src.applied.get("cleanup") in ("none", "auto:otsu")


# ── 4b: cleanup ────────────────────────────────────────────────────────────

def test_merge_readings_keeps_the_most_confident_line_whole():
    a = [{"text": "VOID", "x0": 0, "x1": 50, "top": 0, "bottom": 20, "conf": 30, "line_id": 0},
         {"text": "M3MO", "x0": 100, "x1": 140, "top": 0, "bottom": 20, "conf": 95,
          "line_id": 0}]
    b = [{"text": "1,250.00", "x0": 2, "x1": 52, "top": 1, "bottom": 21, "conf": 91,
          "line_id": 0},
         {"text": "MEMO", "x0": 100, "x1": 140, "top": 0, "bottom": 20, "conf": 80,
          "line_id": 0}]
    got = IC.merge_readings([a, b])
    # one whole line wins - never VOID from one reading and MEMO from another
    assert [w["text"] for w in got] == ["1,250.00", "MEMO"]


def test_every_variant_returns_an_image_of_the_same_page():
    from PIL import Image
    img = Image.new("RGB", (300, 100), (250, 250, 250))
    for v in ("none", "ink", "otsu", "median", "ink_x15"):
        out, f = IC.apply(img, v)
        assert out.width == int(300 * f) and out.height == int(100 * f)


def test_ink_drops_a_saturated_overprint_and_keeps_dark_ink():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (200, 60), (250, 248, 240))
    d = ImageDraw.Draw(img)
    d.rectangle((10, 10, 60, 50), fill=(200, 40, 40))     # red overprint
    d.rectangle((120, 10, 170, 50), fill=(20, 20, 30))    # ink
    out = IC.ink(img)
    assert out.getpixel((35, 30)) == 255 and out.getpixel((145, 30)) == 0


def test_the_default_variant_is_one_that_exists():
    assert IC.DEFAULT in IC.VARIANTS
