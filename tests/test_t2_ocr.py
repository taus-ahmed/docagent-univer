"""Run T2, Stage 4: OCR words in the perception format, through the same
structure path, by a pinned Tesseract release.

The pin tests read files and always run. The OCR tests need a Tesseract
binary and skip without one; in the CI job `ocr-pinned` (env
DOCAGENT_REQUIRE_TESSERACT_PIN=1) the binary MUST be the pinned release."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import ocr_source as O  # noqa: E402
import perception as P  # noqa: E402
import structure_engine as S  # noqa: E402

DOCKER = (ROOT / "Dockerfile.backend").read_text(encoding="utf-8-sig")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _pins(text):
    return dict(re.findall(r"\b(tesseract-ocr(?:-eng|-osd)?|libtesseract5)=(\S+?)(?=\s|\\|$)",
                           text))


# ── the pin, in three places that must agree ────────────────────────────────

def test_the_docker_image_pins_every_tesseract_package():
    pins = _pins(DOCKER)
    assert pins == {"tesseract-ocr": "5.3.0-2", "libtesseract5": "5.3.0-2",
                    "tesseract-ocr-eng": "1:4.1.0-2", "tesseract-ocr-osd": "1:4.1.0-2"}


def test_the_ci_ocr_job_uses_the_same_base_image_and_the_same_pins():
    import yaml
    job = yaml.safe_load(CI)["jobs"]["ocr-pinned"]
    base = re.search(r"^FROM\s+(\S+)", DOCKER, re.M).group(1)
    assert job["container"]["image"] == base
    script = "\n".join(s.get("run", "") for s in job["steps"])
    assert _pins(script) == _pins(DOCKER)
    assert O.TESSERACT_PIN in script


def test_the_code_pin_is_the_packaged_upstream_release():
    assert _pins(DOCKER)["tesseract-ocr"].split("-")[0] == O.TESSERACT_PIN


@pytest.mark.skipif(os.environ.get("DOCAGENT_REQUIRE_TESSERACT_PIN") != "1",
                    reason="only the pinned CI job / the image require the pinned release")
def test_the_reader_this_process_calls_is_the_pinned_release():
    assert O.pin_status()["matches_pin"] is True, O.log_line()


def test_the_job_log_line_names_the_reader_and_the_pin(monkeypatch):
    monkeypatch.setattr(O, "available", lambda: (True, "5.3.0"))
    monkeypatch.setattr(O, "_IDENTITY", {})
    assert O.log_line() == "[OCR] reader tesseract 5.3.0 (pinned 5.3.0): matches the pin"
    monkeypatch.setattr(O, "available", lambda: (True, "5.4.0.20240606"))
    monkeypatch.setattr(O, "_IDENTITY", {})
    assert "DIFFERS from the pin" in O.log_line()


# ── a scanned page through perception and the structure layout ──────────────

needs_ocr = pytest.mark.skipif(not O.available()[0], reason="no Tesseract binary")


def _scan(path, lines):
    """An image-only PDF (no text layer) of printed lines, 200 dpi."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("L", (1700, 2200), 255)
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=34)
    for y, cells in lines:
        for x, text in cells:
            d.text((x, y), text, fill=0, font=font)
    img.save(path, "PDF", resolution=200.0)
    return path


LINES = [(150, [(150, "Item"), (700, "Qty"), (1200, "Amount")]),
         (220, [(150, "Widget"), (700, "2"), (1200, "40.50")]),
         (290, [(150, "Gadget"), (700, "1"), (1200, "12.25")]),
         (360, [(150, "Sprocket"), (700, "5"), (1200, "7.00")])]


@needs_ocr
def test_a_scanned_page_gives_words_in_the_perception_format(tmp_path):
    doc = P.read_document(_scan(tmp_path / "s.pdf", LINES), ocr=True)
    pg = doc["pages"][0]
    assert pg["quality"]["source"] == "ocr" and not pg.get("needs_ocr")
    ws = pg["words"]
    assert ws and all(w["origin"] == "ocr" for w in ws)
    keys = {"id", "text", "x0", "x1", "top", "bottom", "baseline", "size", "bold", "page"}
    assert all(keys <= set(w) for w in ws)
    # boxes are page POINTS (the page is 612 x 792), top-left origin
    assert all(0 <= w["x0"] < w["x1"] <= pg["width"] + 1 for w in ws)
    assert all(0 <= w["top"] < w["bottom"] <= pg["height"] + 1 for w in ws)
    rec = pg["ocr"]
    assert rec["reader"] == "tesseract" and 0.0 <= rec["trust"] <= 1.0
    assert rec["pinned"] == O.TESSERACT_PIN and "matches_pin" in rec
    texts = {w["text"] for w in ws}
    assert {"Widget", "Gadget", "40.50", "12.25"} <= texts


@needs_ocr
def test_a_scanned_page_goes_through_plan_placement_and_verification(tmp_path):
    lay = S.layout_document(P.read_document(_scan(tmp_path / "s.pdf", LINES), ocr=True))
    assert not lay["skipped"]
    cells = lay["pages"][0]
    heads = [c["text"] for c in cells if c.get("kind") == "header"]
    assert heads == ["Item", "Qty", "Amount"]
    row = {c["col"]: c["text"] for c in cells if c["row"] == next(
        c["row"] for c in cells if c["text"] == "Gadget")}
    assert row == {0: "Gadget", 1: "1", 2: "12.25"}
    assert 1 in lay["ocr"]


def test_a_page_not_read_by_ocr_is_skipped_with_its_reason(tmp_path):
    doc = P.read_document(_scan(tmp_path / "s.pdf", LINES), ocr=False)
    assert doc["pages"][0]["needs_ocr"] is True
    lay = S.layout_document(doc)
    assert lay["skipped"] and "not read by OCR" in lay["skipped"][0]


@needs_ocr
def test_a_stored_perception_is_ocrd_later_from_the_file(tmp_path):
    pdf = _scan(tmp_path / "s.pdf", LINES)
    doc = P.unpack(P.pack(P.read_document(pdf, ocr=False)))
    assert P.ocr_pages(doc, pdf) == 1
    assert not S.layout_document(doc)["skipped"]


def test_low_ocr_trust_and_an_off_pin_reader_are_flagged_never_hidden():
    page = {"page": 1, "width": 612, "height": 792, "removed": [], "rules": [],
            "words": [{"id": "w0", "text": "Total", "x0": 10, "x1": 40, "top": 10,
                       "bottom": 20, "baseline": 18, "size": 10, "origin": "ocr"}],
            "lines": [{"id": "l0", "word_ids": ["w0"], "text": "Total", "x0": 10, "x1": 40,
                       "top": 10, "bottom": 20, "baseline": 18, "size": 10, "page": 1}],
            "ocr": {"reader": "tesseract", "reader_version": "5.4.0", "pinned": "5.3.0",
                    "matches_pin": False, "trust": 0.5, "low_confidence_words": 3}}
    lay = S.layout_document({"pages": [page]})
    assert any("trust 0.50" in f for f in lay["flags"])
    assert any("not the pinned 5.3.0" in f for f in lay["flags"])
