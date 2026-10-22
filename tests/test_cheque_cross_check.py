"""The cheque amount cross-check, wired — and a reason on every failed check.

A cheque states its amount twice: in figures and in words. When an extraction
has BOTH, `cheque_amounts.compare_amounts` decides:

  mismatch    BOTH values become exactly low, review_required, "amount_mismatch"
  unreadable  no confidence change; "amount_unreadable" on both values
  match       supporting evidence ONLY — never raises a level; recorded as
              provenance["amount_cross_check"] == "match"

A document without both fields is untouched.

And every value that is low because a check FAILED says so per value, native
included: "grounding_failed", "placement_failed". A native value that passes
everything keeps review_required False and an empty reasons list.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import extractor  # noqa: E402
from app.core.confidence import CONFIDENT_LEVELS, HIGH, LOW, UNVERIFIED  # noqa: E402
from core import preprocessor  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
GRID = {"colWidths": [120] * 26, "merges": {}, "repeatRows": [], "regions": []}
WORDS = "Three Thousand Five Hundred Seventy-Two and 78/100 Dollars"


def _template(*labels):
    return {"layout": {**GRID, "cells": {f"{i},0": {"value": lab, "style": {}}
                                         for i, lab in enumerate(labels)}},
            "doc_type": "cheque", "mode": "layout"}


CHEQUE = _template("Payee", "Amount in Figures", "Amount in Words")


class _Resp:
    def __init__(self, parsed):
        self.success, self.parsed_json = True, parsed
        self.raw_text = json.dumps(parsed)
        self.tokens_used, self.model_used, self.error = 0, "stub", ""


_SLOT = re.compile(r'^\s+(F\d+): .*labelled "(.+)"\s*$', re.M)


def _answer(prompt, resolved):
    fields = {}
    for sid, label in _SLOT.findall(prompt or ""):
        if label in resolved:
            page, line, value = resolved[label]
            fields[sid] = {"value": value, "source": line, "page": page}
    return {"fields": fields}


def _run(path, resolved, template):
    def extract(**kw):
        return _Resp(_answer(kw.get("prompt", ""), resolved))

    (r,) = extractor.run_extraction(
        SimpleNamespace(llm=SimpleNamespace(extract=extract)), path,
        copy.deepcopy(template))
    ed = r.extracted_data
    assert ed.get("extraction_method") == "slot_directed", ed
    refs = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
    return ed, refs


def _gen():
    spec = importlib.util.spec_from_file_location("make_scan_variants", GENERATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _native(tmp_path, lines):
    """A one-page native PDF printing `lines` top to bottom."""
    gen = _gen()
    ops = gen._text_ops([(72, 700 - 30 * i, 11, t) for i, t in enumerate(lines)], 0)
    path = tmp_path / "cheque.pdf"
    path.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0, "ops": ops}]))
    return path


def _cheque(tmp_path, figures, words, template=CHEQUE, answers=None):
    lines = ["Pay to the order of Maria Gonzalez", figures, words]
    resolved = {"Payee": (1, lines[0], "Maria Gonzalez"),
                "Amount in Figures": (1, figures, figures),
                "Amount in Words": (1, words, words)}
    resolved.update(answers or {})
    return _run(_native(tmp_path, lines), resolved, template)


def _schema(p):
    assert "review_reason" not in p, p
    assert isinstance(p["review_reasons"], list), p
    assert p["review_required"] is True or p["review_required"] is False, p


def _both(ed, refs):
    return [(ref, ed["field_provenance"][ref], ed["validation"]["confidence_map"][ref])
            for ref in (refs["Amount in Figures"], refs["Amount in Words"])]


class TestACorrectPair:

    def test_a_match_never_raises_and_is_recorded(self, tmp_path):
        ed, refs = _cheque(tmp_path, "$3,572.78", WORDS)
        for ref, p, lvl in _both(ed, refs):
            _schema(p)
            assert lvl == HIGH, (ref, lvl)              # exactly what it earned
            assert p["amount_cross_check"] == "match", p
            assert p["review_required"] is False and p["review_reasons"] == [], p
        assert ed["needs_review"] is False

    def test_the_unrelated_field_is_untouched(self, tmp_path):
        ed, refs = _cheque(tmp_path, "$3,572.78", WORDS)
        p = ed["field_provenance"][refs["Payee"]]
        assert "amount_cross_check" not in p and p["review_reasons"] == []


class TestAWrongDigit:
    """The Gate 1 shape: $8,572.78 printed where the words say 3,572.78. Both
    ground perfectly — each IS on the page — so nothing else catches it."""

    def test_both_values_become_exactly_low_and_need_review(self, tmp_path):
        ed, refs = _cheque(tmp_path, "$8,572.78", WORDS)
        for ref, p, lvl in _both(ed, refs):
            _schema(p)
            assert p["grounded"] is True, p
            assert lvl == LOW, (ref, lvl)
            assert p["review_required"] is True, p
            assert "amount_mismatch" in p["review_reasons"], p
            assert p["amount_cross_check"] == "mismatch", p
        assert ed["needs_review"] is True
        assert any("amount" in str(f.get("reason", "")).lower()
                   and "words" in str(f.get("reason", "")).lower()
                   for f in ed["validation"]["flagged_fields"]), \
            ed["validation"]["flagged_fields"]


class TestUnreadableWords:

    def test_no_confidence_change_but_a_reason_on_both(self, tmp_path):
        bad = "Thre Thousnd Five Hundred Seventy-Two and 78/100"
        ed, refs = _cheque(tmp_path, "$3,572.78", bad)
        for ref, p, lvl in _both(ed, refs):
            _schema(p)
            assert lvl == HIGH, (ref, lvl)
            assert "amount_unreadable" in p["review_reasons"], p
            assert p["review_required"] is True, p
            assert p["amount_cross_check"] == "unreadable", p
        # The document's review state is exactly what it was without the check.
        assert ed["needs_review"] is False


class TestNoWordsField:

    def test_a_document_without_both_fields_is_untouched(self, tmp_path):
        ed, refs = _cheque(tmp_path, "$8,572.78", WORDS,
                           template=_template("Payee", "Amount in Figures"))
        p = ed["field_provenance"][refs["Amount in Figures"]]
        assert ed["validation"]["confidence_map"][refs["Amount in Figures"]] == HIGH
        assert "amount_cross_check" not in p
        assert p["review_required"] is False and p["review_reasons"] == []
        assert ed["needs_review"] is False


class TestFailedChecksCarryAReason:
    """Native included. A failed check stays low AND says which check."""

    def test_a_grounding_failure_is_named(self, tmp_path):
        ed, refs = _cheque(tmp_path, "$3,572.78", WORDS, answers={
            "Payee": (1, "Pay to the order of Robert Kim", "Robert Kim")})
        ref = refs["Payee"]
        p = ed["field_provenance"][ref]
        _schema(p)
        assert ed["validation"]["confidence_map"][ref] == LOW
        assert p["origin"] == "native"
        assert p["review_required"] is True
        assert "grounding_failed" in p["review_reasons"], p
        assert ed["needs_review"] is True

    def test_a_placement_failure_is_named(self, tmp_path):
        """A matrix template whose heading the page prints: the value read
        sits under the OTHER column."""
        lines = ["Item        2023        2024", "Revenue     100.00      250.00"]
        gen_lines = [(72, 700, 11, "Item"), (250, 700, 11, "2023"),
                     (400, 700, 11, "2024"), (72, 670, 11, "Revenue"),
                     (250, 670, 11, "100.00"), (400, 670, 11, "250.00"),
                     (72, 600, 11, "Statement of operations for the year ended "
                                   "31 December, printed for the placement contract")]
        gen = _gen()
        path = tmp_path / "matrix.pdf"
        path.write_bytes(gen.build_pdf([{"w_pt": 612.0, "h_pt": 792.0,
                                         "ops": gen._text_ops(gen_lines, 0)}]))
        doc = preprocessor.preprocess_file(path)
        line = next(ln for ln in doc.page_texts[0].split("\n") if "Revenue" in ln)
        template = {"layout": {**GRID, "cells": {
            "0,0": {"value": "Item", "style": {}},
            "0,1": {"value": "2023", "style": {}},
            "0,2": {"value": "2024", "style": {}},
            "1,0": {"value": "Revenue", "style": {}}}},
            "doc_type": "other", "mode": "layout"}
        # F1 is Revenue under 2023; answer it with the figure printed under 2024.
        answer = {"fields": {"F1": {"value": "250.00", "source": line.strip(),
                                    "page": 1}}}
        (r,) = extractor.run_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=lambda **kw: _Resp(answer))),
            path, copy.deepcopy(template))
        ed = r.extracted_data
        ref = "B2"
        assert ed["extracted_fields"].get(ref) == "250.00", (ed["extracted_fields"], lines)
        p = ed["field_provenance"][ref]
        _schema(p)
        assert ed["validation"]["confidence_map"][ref] == LOW
        assert ed["validation"]["misplaced_count"] >= 1
        assert p["origin"] == "native", p
        assert p["review_required"] is True
        assert "placement_failed" in p["review_reasons"], p

    def test_a_native_value_that_passes_everything_carries_nothing(self, tmp_path):
        ed, refs = _cheque(tmp_path, "$3,572.78", WORDS)
        for ref, p in ed["field_provenance"].items():
            _schema(p)
            assert p["origin"] == "native"
            assert ed["validation"]["confidence_map"][ref] in CONFIDENT_LEVELS
            assert p["review_required"] is False and p["review_reasons"] == [], p


# ── the real pre-OCR fixture (Gate 1) ─────────────────────────────────────────

@pytest.fixture(scope="module")
def variants(tmp_path_factory):
    out = tmp_path_factory.mktemp("scan_variants_amounts")
    proc = subprocess.run([sys.executable, str(GENERATOR), "--out", str(out),
                           "--repo", str(bs.REPO_DIR), "--verify"],
                          capture_output=True)
    said = (proc.stdout.decode("utf-8", "replace")
            + proc.stderr.decode("utf-8", "replace"))
    assert proc.returncode == 0 and "verify: ok" in said, said
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    return out, {v["file"][:-len(".pdf")]: v for v in manifest["variants"]}


class TestTheGarbledPreOcrCheque:
    """`preocr_garbled` page 2 is chk_002 ($3,572.78, "three thousand five
    hundred seventy-two and 78/100") under an embedded text layer whose
    figures are deliberately wrong. Before the cross-check, the wrong figure
    was merely `unverified`, like every other pre-OCR value."""

    def test_the_wrong_figure_and_its_words_are_low_with_the_reason(self, variants):
        path = variants[0] / "preocr_garbled.pdf"
        entry = variants[1]["preocr_garbled"]
        page = 2
        cheque = entry["pages"][page - 1]["cheques"][0]
        assert cheque["fields"]["amount_numeral"] == "3,572.78", cheque["fields"]
        layer = {f["field"]: f for f in cheque["text_layer"]["fields"]}
        wrong = layer["amount_numeral"]["in_layer"]
        assert not layer["amount_numeral"]["matches_truth"], wrong
        words = layer["amount_words_shown"]["in_layer"]
        doc = preprocessor.preprocess_file(path)
        text = doc.page_texts[page - 1].split("\n")
        fig_line = next(ln for ln in text if wrong in ln).strip()
        words_line = next(ln for ln in text if words in ln).strip()
        ed, refs = _run(path, {"Amount in Figures": (page, fig_line, wrong),
                               "Amount in Words": (page, words_line, words)},
                        _template("Amount in Figures", "Amount in Words"))
        for ref, p, lvl in _both(ed, refs):
            _schema(p)
            assert lvl == LOW, (ref, lvl, p)            # not merely unverified
            assert lvl != UNVERIFIED
            assert p["review_required"] is True
            assert "amount_mismatch" in p["review_reasons"], p
        assert ed["needs_review"] is True
