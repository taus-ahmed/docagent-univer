"""Gate 4c — the MICR routing number and its ABA checksum, recorded per value.

`parse_micr` already refuses a transit field that fails the ABA checksum — and
said so to nobody: the routing slot simply stayed empty, unflagged, exactly as
if the band had never been printed. And a routing number the MODEL answered
was never checked at all, so nine digits that cannot be a routing number were
written at `high`.

Now: every filled routing slot records `aba_checksum` ("pass" | "fail") in
its provenance; a failing one is exactly low with "checksum_failed"; a band
whose routing number was withheld for failing is flagged and needs review
("empty and flagged"); `validation.routing_checksum` says what the band held.
Leading zeros survive (`021000021`, serial `001847`).
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
import ocr_source  # noqa: E402
from app.core.confidence import CONFIDENT_LEVELS, HIGH, LOW  # noqa: E402
from micr import aba_is_valid, parse_micr  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
GRID = {"colWidths": [120] * 26, "merges": {}, "repeatRows": [], "regions": []}
TEMPLATE = {"layout": {**GRID, "cells": {
    "0,0": {"value": "Payee", "style": {}},
    "1,0": {"value": "Routing Number", "style": {}},
    "2,0": {"value": "Account Number", "style": {}}}},
    "doc_type": "cheque", "mode": "layout"}
VALID, INVALID = "021000021", "123456789"
assert aba_is_valid(VALID) and not aba_is_valid(INVALID)


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)


def _run(path, answers, template=TEMPLATE):
    def extract(**kw):
        fields = {}
        for sid, label in _SLOT.findall(kw.get("prompt") or ""):
            if label in answers:
                src, val = answers[label]
                fields[sid] = {"value": val, "source": src, "page": 1}
        return _Resp({"fields": fields})

    (r,) = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
        copy.deepcopy(template))
    ed = r.extracted_data
    refs = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
    return ed, refs


def _cheque(tmp_path, routing):
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    band = f"A{routing}A C7743882201C 001847D"
    lines = ["Pay to the order of Maria Gonzalez",
             "Golden Plains Credit Union, cheque printed for the MICR contract",
             f"Bank routing {routing}",
             band]
    ops = gen._text_ops([(72, 700 - 30 * i, 11, t) for i, t in enumerate(lines)], 0)
    path = tmp_path / "cheque.pdf"
    path.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": ops}]))
    return path, lines, band


PAYEE = {"Payee": ("Pay to the order of Maria Gonzalez", "Maria Gonzalez")}


class TestLeadingZerosSurvive:

    def test_routing_and_serial_keep_their_zeros(self):
        """GUARD, unmarked — true today."""
        got = parse_micr("A021000021A C7743882201C 001847D")
        assert got == {"routing_number": "021000021",
                       "account_number": "7743882201", "serial_number": "001847"}

    def test_a_routing_number_read_from_the_band_records_its_checksum(self, tmp_path):
        path, _lines, _band = _cheque(tmp_path, VALID)
        ed, refs = _run(path, PAYEE)
        ref = refs["Routing Number"]
        assert ed["extracted_fields"][ref] == VALID
        p = ed["field_provenance"][ref]
        assert p["aba_checksum"] == "pass", p
        assert ed["validation"]["confidence_map"][ref] == HIGH
        assert p["review_required"] is False and p["review_reasons"] == []
        assert ed["validation"]["routing_checksum"] == "pass"


class TestAFailingChecksum:

    def test_a_withheld_band_routing_number_is_flagged_not_silent(self, tmp_path):
        path, _lines, _band = _cheque(tmp_path, INVALID)
        ed, refs = _run(path, PAYEE)
        assert refs["Routing Number"] not in ed["extracted_fields"]
        assert ed["validation"]["routing_checksum"] == "fail"
        assert any("checksum" in f["reason"].lower() and f["value"] == INVALID
                   for f in ed["validation"]["flagged_fields"]), \
            ed["validation"]["flagged_fields"]
        assert ed["needs_review"] is True

    def test_a_model_answer_that_fails_is_exactly_low_with_the_reason(self, tmp_path):
        path, lines, _band = _cheque(tmp_path, INVALID)
        ed, refs = _run(path, {**PAYEE, "Routing Number": (lines[2], INVALID)})
        ref = refs["Routing Number"]
        p = ed["field_provenance"][ref]
        assert p["grounded"] is True, p                  # it IS on the page
        assert ed["validation"]["confidence_map"][ref] == LOW
        assert p["aba_checksum"] == "fail"
        assert p["review_required"] is True
        assert "checksum_failed" in p["review_reasons"], p
        assert ed["needs_review"] is True

    def test_a_model_answer_that_passes_keeps_its_level(self, tmp_path):
        path, lines, _band = _cheque(tmp_path, VALID)
        ed, refs = _run(path, {**PAYEE, "Routing Number": (lines[2], VALID)})
        ref = refs["Routing Number"]
        assert ed["validation"]["confidence_map"][ref] in CONFIDENT_LEVELS
        assert ed["field_provenance"][ref]["aba_checksum"] == "pass"


try:
    ocr_source._configure()
    HAS_TESSERACT = True
except Exception:  # pragma: no cover - environment dependent
    HAS_TESSERACT = False


@pytest.mark.skipif(not HAS_TESSERACT, reason="no tesseract binary")
def test_the_real_invalid_checksum_cheque_is_flagged():
    """chk_009 is the source set's intentional invalid-checksum case."""
    rec = next(r for r in json.loads((bs.TESTS_DIR / "test_OCR" / "_index.json")
                                     .read_text(encoding="utf-8"))
               if r["id"] == "chk_009")
    assert rec["intentional_invalid_checksum_test_case"] is True
    # The MODERATE scan: OCR reads its band whole. On the clean one it reads
    # the transit sentinel as "AG", so no transit field is found at all —
    # see the Gate 4c measurement in the report.
    ed, refs = _run(bs.TESTS_DIR / "test_OCR" / rec["files"]["moderate"], {})
    assert refs["Routing Number"] not in ed["extracted_fields"]
    assert ed["validation"]["routing_checksum"] == "fail"
    assert any("checksum" in f["reason"].lower()
               for f in ed["validation"]["flagged_fields"])
