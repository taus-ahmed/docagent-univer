"""
Confidence calibration (Phase 5).

A confidence level is only worth showing a user if it predicts correctness.
These tests pin the two things that make "high" mean something — grounding and
one-datum-per-cell — plus the document-level gate, and the rule that a level
never leaks into the exported file.
"""
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from app.core.confidence import (  # noqa: E402
    CONFIDENT_LEVELS, GROUNDED, HIGH, LOW, UNVERIFIED,
)
from slot_extractor import (  # noqa: E402
    _single_datum, confidence_for, run_slot_extraction,
)

PAGE = ("NEXUS GLOBAL TRADING PAY STUB\n"
        "Bill To: Apex Industrial Supplies Inc.\n"
        "Mr. Robert Chen - rchen@apexindustrial.com\n"
        "Ms. Linda Zhao | (310) 555-0233\n"
        "Closing Balance: $125,357.26\n"
        "Contact: (212) 555-0148\n"
        "Email: ar@nexusglobaltrading.com")


class TestSingleDatum:
    def test_a_plain_value_is_one_datum(self):
        assert _single_datum("Apex Industrial Supplies Inc.", "Bill To Company")

    def test_a_name_with_an_email_is_two(self):
        assert not _single_datum("Mr. Robert Chen - rchen@apexindustrial.com",
                                 "Bill To Contact")

    def test_a_name_with_a_phone_is_two(self):
        assert not _single_datum("Ms. Linda Zhao | (310) 555-0233",
                                 "Vendor Contact")

    def test_a_pipe_alone_is_enough_to_disqualify(self):
        assert not _single_datum("Acme Ltd | Dept 4", "Vendor")

    def test_a_field_that_asks_for_an_email_may_contain_one(self):
        assert _single_datum("ar@nexusglobaltrading.com", "Email")

    def test_a_field_that_asks_for_a_phone_may_contain_one(self):
        assert _single_datum("(212) 555-0148", "Phone")

    def test_a_number_is_never_two_data(self):
        assert _single_datum("125,357.26", "Closing Balance")


class TestConfidenceFor:
    def test_ungrounded_is_never_high(self):
        lvl, why = confidence_for("anything", "some span", "Label", False)
        assert lvl == LOW and "ground" in why

    def test_grounded_single_datum_is_high(self):
        lvl, _ = confidence_for("125,357.26", "Closing Balance: $125,357.26",
                                "Closing Balance", True)
        assert lvl == HIGH

    def test_grounded_but_two_data_is_demoted(self):
        lvl, why = confidence_for("Mr. Robert Chen - rchen@apex.com",
                                  "Mr. Robert Chen - rchen@apex.com",
                                  "Bill To Contact", True)
        assert lvl == LOW
        assert "more than one piece of information" in why

    def test_the_reason_is_always_stated(self):
        for args in (("x", "y", "L", False),
                     ("a | b", "a | b", "L", True)):
            lvl, why = confidence_for(*args)
            assert lvl == LOW and why


class TestInferredIsNeverHigh:
    """Phase 8. Grounding proves the text came from the document; it never
    proves the value belongs in the slot. With an inferred template the slot's
    label was written by the same model chain that produced the value, so
    "high" would assert something nothing checks."""

    def test_an_inferred_cell_is_grounded_not_high(self):
        lvl, _ = confidence_for("125,357.26", "Closing Balance: $125,357.26",
                                "Closing Balance", True, inferred=True)
        assert lvl == GROUNDED
        assert lvl != HIGH

    def test_grounded_still_counts_as_confident(self):
        assert GROUNDED in CONFIDENT_LEVELS and HIGH in CONFIDENT_LEVELS

    def test_an_inferred_cell_can_still_be_low(self):
        lvl, why = confidence_for("anything", "not in the doc", "Label", False,
                                  inferred=True)
        assert lvl == LOW and why

    def test_two_data_in_an_inferred_cell_is_still_low(self):
        lvl, _ = confidence_for("Mr. Robert Chen - rchen@apex.com",
                                "Mr. Robert Chen - rchen@apex.com",
                                "Bill To Contact", True, inferred=True)
        assert lvl == LOW

    def test_the_two_confident_levels_are_never_the_same_word(self):
        """The whole point of the split: a reader must be able to tell a
        user-authored slot from a model-named one."""
        assert HIGH != GROUNDED

    def test_unverified_is_not_a_confident_level(self):
        """No text layer means nothing was checked — which is not the same as
        a check that came out middling, and not something to stand behind."""
        assert UNVERIFIED not in CONFIDENT_LEVELS


def _stub(payload):
    class _Resp:
        raw_text = json.dumps(payload)
        parsed_json = payload
        success = True
        tokens_used = 0
        model_used = "stub"

    class _LLM:
        def extract(self, **kw):
            return _Resp()

    return type("O", (), {"llm": _LLM()})()


def _grid(cells):
    return {"cells": {k: {"value": v} for k, v in cells.items()},
            "colWidths": [], "merges": {}, "repeatRows": []}


GRID = _grid({f"{i},0": lbl for i, lbl in enumerate(
    ["Bank", "Contact", "Payee", "Balance", "Ref"])}
    | {f"{i},1": "" for i in range(5)})


def _run(fields):
    return run_slot_extraction(
        _stub({"fields": fields}), "D.pdf", {"layout": GRID}, None,
        page_images=[], doc_text=PAGE, doc_text_pages=[PAGE],
        file_type="digital_pdf", default_doc_type="other", start=0.0)[0]


class TestDocumentGate:
    """More than 30% low-confidence cells marks the document for review as a
    whole, instead of a wall of per-cell warnings."""

    def _answer(self, n_bad):
        line = "Ms. Linda Zhao | (310) 555-0233"
        good = "Closing Balance: $125,357.26"
        out = {}
        for i in range(5):
            sid = f"F{i + 1}"
            if i < n_bad:
                out[sid] = {"value": line, "source": line, "page": 1}
            else:
                out[sid] = {"value": "125,357.26", "source": good, "page": 1}
        return out

    def test_a_clean_document_does_not_trip_the_gate(self):
        v = _run(self._answer(0)).extracted_data["validation"]
        assert v["low_confidence_cells"] == 0
        assert v["document_needs_review"] is False

    def test_one_bad_cell_in_five_does_not_trip_it(self):
        v = _run(self._answer(1)).extracted_data["validation"]
        assert v["low_confidence_ratio"] == pytest.approx(0.2)
        assert v["document_needs_review"] is False

    def test_more_than_thirty_percent_trips_it(self):
        v = _run(self._answer(2)).extracted_data["validation"]
        assert v["low_confidence_ratio"] == pytest.approx(0.4)
        assert v["document_needs_review"] is True

    def test_tripping_the_gate_marks_the_whole_document(self):
        r = _run(self._answer(3))
        assert r.extracted_data["needs_review"] is True
        assert r.extracted_data["overall_confidence"] == "low"
        assert any("needs manual review" in n
                   for n in r.extracted_data["validation_notes"])


class TestExportCarriesNoConfidence:
    """Confidence is surfaced in the app. The exported file is values only —
    no annotations, no scores, no colour that survives export."""

    def test_the_sheet_holds_values_and_nothing_else(self):
        import contextlib
        import io as _io

        import openpyxl
        from app.api.routes.extract import _write_slot_excel
        from app.models.models import DocumentResult

        r = _run(self._mixed())
        doc = DocumentResult(filename="D.pdf", document_type="other",
                             extraction_json=json.dumps(r.extracted_data,
                                                        default=str))
        wb = openpyxl.Workbook()
        ws = wb.active
        with contextlib.redirect_stdout(_io.StringIO()):
            _write_slot_excel(ws, [doc], GRID, GRID["cells"], openpyxl)

        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                text = str(c.value).casefold()
                for banned in ("confidence", "high", "low", "needs review",
                               "unverified", "flag"):
                    assert banned not in text, (c.coordinate, c.value)
                assert c.fill.fgColor.rgb in (None, "00000000")
                assert not c.comment

    def _mixed(self):
        line = "Ms. Linda Zhao | (310) 555-0233"
        good = "Closing Balance: $125,357.26"
        return {"F1": {"value": line, "source": line, "page": 1},
                "F2": {"value": "125,357.26", "source": good, "page": 1}}
