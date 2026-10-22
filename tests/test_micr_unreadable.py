"""Reason code `micr_band_unreadable` — a cheque whose MICR band cannot be read.

A band-shaped line whose digits did not survive (`A423S11G18A C5S94O78l6184C`)
says "this is a cheque, and its routing and account are printed HERE" — and
then says nothing about what they are. The values that depend on the band's
identity (routing, account) must say so per value: distinct from
`checksum_failed` (the digits were read and are wrong) and from
`possible_multiple_documents` (the count of cheques is unknown).

A filled identity value carries the reason with review_required True; an
identity slot left empty is flagged ("empty and flagged"); the record needs
review. A record whose band WAS read carries no such reason.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
from types import SimpleNamespace

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
GRID = {"colWidths": [120] * 26, "merges": {}, "repeatRows": [], "regions": []}
TEMPLATE = {"layout": {**GRID, "cells": {
    "0,0": {"value": "Payee", "style": {}},
    "1,0": {"value": "Routing Number", "style": {}},
    "2,0": {"value": "Account Number", "style": {}}}},
    "doc_type": "cheque", "mode": "layout"}
UNREADABLE = "C001009C A423S11G18A C5S94O78l6184C"
READABLE = "C001002C A423511613A 559407816184C"
_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


def _run(tmp_path, band, answers):
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    lines = ["Pay to the order of Maria Gonzalez",
             "Golden Plains Credit Union, cheque printed for the MICR contract",
             "Bank routing 021000021", band]
    ops = gen._text_ops([(72, 700 - 30 * i, 11, t) for i, t in enumerate(lines)], 0)
    path = tmp_path / "cheque.pdf"
    path.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": ops}]))

    def extract(**kw):
        fields = {}
        for sid, label in _SLOT.findall(kw.get("prompt") or ""):
            if label in answers:
                src, val = answers[label]
                fields[sid] = {"value": val, "source": src, "page": 1}
        return _Resp({"fields": fields})

    (r,) = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
        copy.deepcopy(TEMPLATE))
    ed = r.extracted_data
    return ed, {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}


ANSWERS = {"Payee": ("Pay to the order of Maria Gonzalez", "Maria Gonzalez"),
           "Routing Number": ("Bank routing 021000021", "021000021")}


def test_an_unreadable_band_marks_the_identity_values(tmp_path):
    ed, refs = _run(tmp_path, UNREADABLE, ANSWERS)
    p = ed["field_provenance"][refs["Routing Number"]]
    assert p["review_required"] is True
    assert "micr_band_unreadable" in p["review_reasons"], p
    assert "checksum_failed" not in p["review_reasons"]
    assert "possible_multiple_documents" not in p["review_reasons"]
    # A value that does not depend on the band is not touched.
    payee = ed["field_provenance"][refs["Payee"]]
    assert "micr_band_unreadable" not in payee["review_reasons"]
    # The empty identity slot is flagged, not silent.
    assert refs["Account Number"] not in ed["extracted_fields"]
    assert any("micr" in f["reason"].lower() and f["ref"] == "Account Number"
               for f in ed["validation"]["flagged_fields"]), \
        ed["validation"]["flagged_fields"]
    assert ed["validation"]["micr_band_unreadable"] is True
    assert ed["needs_review"] is True


def test_a_readable_band_carries_no_such_reason(tmp_path):
    ed, refs = _run(tmp_path, READABLE, ANSWERS)
    assert "micr_band_unreadable" not in json.dumps(ed["field_provenance"])
    assert not ed["validation"].get("micr_band_unreadable")
