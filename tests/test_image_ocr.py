"""Gate 4a / 4d — a standalone image goes through the SAME reader seam as a scan.

An uploaded JPG/PNG used to reach the engine as a picture and nothing else:
`_process_image` produced one base64 image, no text, no geometry, no page
origin, so slot extraction had nothing to ground against and floored every
value to `unverified` without a single check — and the route sent images to a
vision-only path that never called the engine at all.

Now the engine reads an image exactly as it reads a scanned page: OCR words
with geometry through `read_page`, page origin "ocr", grounded values exactly
`unverified`, failed checks `low` with their reason, per-value review metadata,
OCR metadata in the result.

4d — handwriting is not read. A value the model saw only in the image (no OCR
text to ground it against) is exactly low, flagged, and never high.

Real files: tests/test_OCR (the source cheque images, truth in _index.json).
"""
from __future__ import annotations

import copy
import json
import re
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
import ocr_source  # noqa: E402
from app.core.confidence import CONFIDENT_LEVELS, LOW, UNVERIFIED  # noqa: E402
from core.preprocessor import preprocess_file  # noqa: E402

OCR_DIR = bs.TESTS_DIR / "test_OCR"
INDEX = {r["id"]: r for r in json.loads((OCR_DIR / "_index.json")
                                        .read_text(encoding="utf-8"))}
REC = INDEX["chk_002"]
IMAGES = {"jpg": OCR_DIR / REC["files"]["moderate"],
          "png": OCR_DIR / REC["files"]["clean"]}
GRID = {"colWidths": [120] * 26, "merges": {}, "repeatRows": [], "regions": []}
TEMPLATE = {"layout": {**GRID, "cells": {
    "0,0": {"value": "Payee", "style": {}},
    "1,0": {"value": "Memo", "style": {}},
    "2,0": {"value": "Signature", "style": {}}}},
    "doc_type": "cheque", "mode": "layout"}

try:
    ocr_source._configure()
    HAS_TESSERACT = True
except Exception:  # pragma: no cover - environment dependent
    HAS_TESSERACT = False
pytestmark = pytest.mark.skipif(not HAS_TESSERACT, reason="no tesseract binary")


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)


def _line_with(text, needle):
    return next(ln.strip() for ln in text.split("\n") if needle in ln)


_DOCS: dict = {}


def _doc(kind):
    if kind not in _DOCS:
        _DOCS[kind] = preprocess_file(IMAGES[kind])
    return _DOCS[kind]


def _run(kind):
    doc = _doc(kind)
    text = doc.page_texts[0]
    payee_line = _line_with(text, REC["payee"].split()[-1])
    answers = {"Payee": (payee_line, REC["payee"]),
               # What the OCR text cannot show: a value the model could only
               # have read from the picture (a handwritten signature).
               "Signature": ("Signed: Maria Gonzalez-Ruiz", "M. Gonzalez-Ruiz")}

    def extract(**kw):
        fields = {}
        for sid, label in _SLOT.findall(kw.get("prompt") or ""):
            if label in answers:
                src, val = answers[label]
                fields[sid] = {"value": val, "source": src, "page": 1}
        return _Resp({"fields": fields})

    (r,) = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), IMAGES[kind],
        copy.deepcopy(TEMPLATE))
    ed = r.extracted_data
    assert ed.get("extraction_method") == "slot_directed", ed
    refs = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
    return ed, refs


@pytest.mark.parametrize("kind", ["jpg", "png"])
class TestAnImageIsReadLikeAScan:

    def test_ocr_words_with_geometry_and_origin_ocr(self, kind):
        doc = _doc(kind)
        assert doc.file_type == "image"
        assert doc.page_origins == ["ocr"]
        words = [w for ln in doc.page_lines[0] for w in ln]
        assert len(words) >= 10, len(words)
        assert all({"x0", "x1", "top", "bottom"} <= w.keys() for w in words)
        assert REC["payee"].split()[-1] in doc.page_texts[0]
        (rec,) = doc.ocr_pages
        assert rec["page"] == 1 and rec["words"] == len(words)
        assert rec["skew_detector"] == "dark" and rec["retry"] in ("none", "crop_psm6")
        assert doc.page_images_b64, "the model still gets the picture"

    def test_a_grounded_value_is_exactly_unverified(self, kind):
        ed, refs = _run(kind)
        ref = refs["Payee"]
        p = ed["field_provenance"][ref]
        assert p["grounded"] is True, p
        assert ed["validation"]["confidence_map"][ref] == UNVERIFIED
        assert p["origin"] == "ocr"
        assert p["review_required"] is True and p["review_reasons"] == ["ocr_origin"]
        assert ed["needs_review"] is True
        assert ed["validation"]["ocr_pages"][0]["page"] == 1
        assert {int(k): v for k, v in ed["validation"]["page_origins"].items()} == {1: "ocr"}

    def test_an_image_only_value_is_low_flagged_never_high(self, kind):
        """4d — handwriting is not read; its value cannot be grounded."""
        ed, refs = _run(kind)
        ref = refs["Signature"]
        p = ed["field_provenance"][ref]
        lvl = ed["validation"]["confidence_map"][ref]
        assert lvl == LOW and lvl not in CONFIDENT_LEVELS
        assert p["review_required"] is True
        assert p["review_reasons"][0] == "ocr_origin"
        assert "grounding_failed" in p["review_reasons"], p
        assert any(f["value"] == "M. Gonzalez-Ruiz"
                   for f in ed["validation"]["flagged_fields"])
