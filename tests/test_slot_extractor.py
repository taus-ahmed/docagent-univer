"""
Unit tests for slot-directed extraction. Offline (LLM stubbed), always green.

The grounding check and the duplicate-row guard both fail SILENTLY when
broken — a check that accepts everything looks exactly like a document that
extracted cleanly — so they are tested directly rather than inferred from an
accuracy number.
"""
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from slot_extractor import (  # noqa: E402
    build_prompt, enumerate_slots, run_slot_extraction, verify_span,
)

PAGE = ("FIRST NATIONAL BANK OF NEW YORK ACCOUNT STATEMENT\n"
        "Account Holder: Nexus Global Trading LLC\n"
        "01/03 DEP Wire deposit - Summit Retail Group $15,000.00 $199,320.55\n"
        "01/05 ACH Payroll disbursement - January wk1 $18,450.00 $180,870.55\n"
        "Closing Balance: $125,357.26")


def _grid(cells):
    return {"cells": {k: {"value": v, "extractTarget": False}
                      for k, v in cells.items()},
            "colWidths": [], "merges": {}, "extractTargets": [], "repeatRows": []}


class TestEnumeration:
    def test_kv_rows_become_field_slots(self):
        s = enumerate_slots(_grid({"0,0": "Bank Name", "0,1": "",
                                   "1,0": "Account Holder", "1,1": ""}))
        assert [f["row_label"] for f in s["fields"]] == ["Bank Name", "Account Holder"]
        assert [f["ref"] for f in s["fields"]] == ["B1", "B2"]
        assert s["tables"] == []

    def test_header_row_with_empty_band_becomes_a_table(self):
        cells = {"0,0": "Date", "0,1": "Type", "0,2": "Amount",
                 "5,0": "Total", "5,1": ""}
        s = enumerate_slots(_grid(cells))
        assert len(s["tables"]) == 1
        t = s["tables"][0]
        assert [c["header"] for c in t["columns"]] == ["Date", "Type", "Amount"]
        assert (t["header_row"], t["start_row"], t["end_row"]) == (0, 1, 4)
        # the totals row below the band is a FIELD slot, not part of the table:
        # a total and a line item are different addresses and are asked for
        # separately, which is what removes total-vs-line ambiguity.
        assert [f["row_label"] for f in s["fields"]] == ["Total"]

    def test_a_labelled_row_is_never_mistaken_for_a_table_header(self):
        """Two static cells side by side with a static cell below them is a
        stack of labels, not a table header."""
        s = enumerate_slots(_grid({"0,0": "Vendor", "0,1": "Acme",
                                   "1,0": "Buyer", "1,1": "Nexus"}))
        assert s["tables"] == []

    def test_real_bank_statement_template(self):
        grid = json.loads((bs.TEMPLATES_DIR / "bank_statement.json").read_text())
        s = enumerate_slots(grid)
        assert len(s["fields"]) == 10
        assert len(s["tables"]) == 1
        assert [c["header"] for c in s["tables"][0]["columns"]] == [
            "Date", "Type", "Description", "Debit", "Credit", "Balance"]

    def test_empty_grid_is_safe(self):
        assert enumerate_slots({"cells": {}}) == {"fields": [], "tables": []}

    def test_header_with_no_band_beneath_it_is_not_guessed_at(self):
        """"Date | Amount" as the last row of a grid is indistinguishable from
        a label/value pair, so it is not treated as a table. The engine logs
        that it skipped it; Phase 2a's stored shape removes the ambiguity."""
        s = enumerate_slots(_grid({"0,0": "Bank Name", "0,1": "",
                                   "2,0": "Date", "2,1": "Amount"}))
        assert s["tables"] == []


class TestGrounding:
    def test_value_inside_its_span_is_grounded(self):
        ok, _ = verify_span("$15,000.00", PAGE.splitlines()[2], 1, [PAGE])
        assert ok is True

    def test_value_not_in_its_own_span_is_rejected(self):
        ok, why = verify_span("$99,999.99", PAGE.splitlines()[2], 1, [PAGE])
        assert ok is False and "own source span" in why

    def test_span_absent_from_document_is_rejected(self):
        ok, why = verify_span("$15,000.00", "01/04 ACH Fabricated $15,000.00",
                              1, [PAGE])
        assert ok is False and "not found in document" in why

    def test_missing_span_is_rejected(self):
        ok, why = verify_span("$15,000.00", "", 1, [PAGE])
        assert ok is False and "no source span" in why

    def test_empty_answer_needs_no_grounding(self):
        assert verify_span("", "", 0, [PAGE])[0] is True

    def test_number_formatting_differences_still_ground(self):
        assert verify_span("15000.00", PAGE.splitlines()[2], 1, [PAGE])[0] is True

    def test_wrong_page_falls_back_to_other_pages(self):
        assert verify_span("$15,000.00", PAGE.splitlines()[2], 9, [PAGE])[0] is True


def _stub(payload):
    """An orchestrator whose LLM returns one fixed JSON payload."""
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


BANK_GRID = _grid({
    "0,0": "Bank Name", "0,1": "",
    "2,0": "Date", "2,1": "Amount",     # table header, band = rows 3-5
    "6,0": "Closing Balance", "6,1": "",
})
# A two-column band is a label/value pair by construction, so the shape names
# it after its label column ("Date") rather than positionally.
BAND = "Date"


def _run(payload):
    return run_slot_extraction(
        _stub(payload), "STMT.pdf", {"layout": BANK_GRID}, None,
        page_images=[], doc_text=PAGE, doc_text_pages=[PAGE],
        file_type="digital_pdf", default_doc_type="bank_statement",
        start=0.0)[0]


class TestRun:
    def test_answer_is_written_to_the_slot_it_was_asked_for(self):
        r = _run({"fields": {"F1": {
            "value": "FIRST NATIONAL BANK OF NEW YORK",
            "source": "FIRST NATIONAL BANK OF NEW YORK ACCOUNT STATEMENT",
            "page": 1}}})
        assert r.extracted_data["extracted_fields"] == {
            "B1": "FIRST NATIONAL BANK OF NEW YORK"}
        assert r.extracted_data["validation"]["confidence_map"]["B1"] == "high"

    def test_ungrounded_value_is_kept_but_not_confident(self):
        r = _run({"fields": {"F1": {"value": "Invented Bank PLC",
                                    "source": "Invented Bank PLC", "page": 1}}})
        ed = r.extracted_data
        assert ed["extracted_fields"]["B1"] == "Invented Bank PLC"
        assert ed["validation"]["confidence_map"]["B1"] == "low"
        assert ed["validation"]["ungrounded_count"] == 1
        assert ed["needs_review"] is True

    def test_answer_for_an_unknown_slot_is_discarded(self):
        r = _run({"fields": {"F99": {"value": "x", "source": PAGE, "page": 1}}})
        assert r.extracted_data["extracted_fields"] == {}
        assert any("unknown slot" in n for n in r.extracted_data["validation_notes"])

    def test_duplicate_row_claiming_the_same_source_line_is_dropped(self):
        """The phantom-row failure mode: a fabricated row is a second row
        claiming a line another row already used."""
        line = PAGE.splitlines()[2]
        r = _run({"tables": {BAND: [
            {"cells": {"Date": "01/03", "Amount": "$15,000.00"}, "source": line, "page": 1},
            {"cells": {"Date": "01/03", "Amount": "$15,000.00"}, "source": line, "page": 1},
        ]}})
        rows = r.extracted_data[f"{BAND}_rows"]
        assert len(rows) == 1
        assert any("duplicate row dropped" in n
                   for n in r.extracted_data["validation_notes"])

    def test_blank_cell_stays_blank_and_is_not_filled_from_a_neighbour(self):
        line = PAGE.splitlines()[2]
        r = _run({"tables": {BAND: [
            {"cells": {"Date": "01/03", "Amount": ""}, "source": line, "page": 1}]}})
        assert r.extracted_data[f"{BAND}_rows"][0]["Amount"] == ""

    def test_two_distinct_rows_both_survive(self):
        lines = PAGE.splitlines()
        r = _run({"tables": {BAND: [
            {"cells": {"Date": "01/03", "Amount": "$15,000.00"}, "source": lines[2], "page": 1},
            {"cells": {"Date": "01/05", "Amount": "$18,450.00"}, "source": lines[3], "page": 1},
        ]}})
        assert len(r.extracted_data[f"{BAND}_rows"]) == 2

    def test_unparseable_response_fails_the_document_loudly(self):
        r = run_slot_extraction(
            _stub(None), "STMT.pdf", {"layout": BANK_GRID}, None,
            page_images=[], doc_text=PAGE, doc_text_pages=[PAGE],
            file_type="digital_pdf", default_doc_type="bank_statement", start=0.0)[0]
        assert r.success is False

    def test_unanswered_slots_are_reported_not_hidden(self):
        r = _run({"fields": {}})
        assert any("returned no value" in n
                   for n in r.extracted_data["validation_notes"])


class TestPrompt:
    def test_prompt_addresses_every_slot_and_names_every_column(self):
        grid = json.loads((bs.TEMPLATES_DIR / "bank_statement.json").read_text())
        p = build_prompt(enumerate_slots(grid), [PAGE], "bank_statement")
        for label in ["Bank Name", "Closing Balance", "Opening Balance"]:
            assert label in p
        assert "Date | Type | Description | Debit | Credit | Balance" in p
        assert "source" in p and "verbatim" in p
        assert PAGE.splitlines()[0] in p  # the document text is supplied
