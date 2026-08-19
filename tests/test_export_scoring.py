"""
Tests for export-level scoring — the check that reads the .xlsx a user
receives and scores THAT, rather than the engine's in-memory result.

This exists because a real writer bug produced 34 correct labels and 34 empty
cells while extraction held every value, and nothing caught it: the harness
only ever scored the result object. A check that cannot detect that bug is
worse than none, so the detection itself is tested here — with a sheet
deliberately written the broken way.
"""
import json

import openpyxl
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.harness.scoring import score_document  # noqa: E402
from tests.harness.sheet_reader import read_sheet, sheet_as_result  # noqa: E402
from template_shape import compute_shape  # noqa: E402

GRID = {"cells": {
    "0,0": {"value": "Bank Name"}, "0,1": {"value": ""},
    "1,0": {"value": "Statement No"}, "1,1": {"value": ""},
    "3,0": {"value": "Date"}, "3,1": {"value": "Amount"},
    "4,0": {"value": ""}, "4,1": {"value": ""},
    "5,0": {"value": ""}, "5,1": {"value": ""},
    "7,0": {"value": "Closing Balance"}, "7,1": {"value": ""},
}}

LABEL = {
    "document_id": "T", "document_type": "bank_statement",
    "fields": {"Bank Name": "First National", "Statement No": "STMT-1",
               "Closing Balance": 125357.26},
    "field_types": {"Closing Balance": "money"},
    "tables": {"Date": [{"Date": "01/03", "Amount": 15000.0},
                        {"Date": "01/05", "Amount": 18450.0}]},
    "table_types": {"Date": {"Date": "date", "Amount": "money"}},
}


def _shape():
    return compute_shape(GRID)


def _sheet(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r, cols in rows.items():
        for c, v in cols.items():
            ws.cell(row=r + 1, column=c + 1).value = v
    return ws


GOOD = {
    0: {0: "Bank Name", 1: "First National"},
    1: {0: "Statement No", 1: "STMT-1"},
    3: {0: "Date", 1: "Amount"},
    4: {0: "01/03", 1: 15000.0},
    5: {0: "01/05", 1: 18450.0},
    7: {0: "Closing Balance", 1: 125357.26},
}

# The actual bug: every label written, every value cell left empty.
LABELS_ONLY = {r: {0: cols[0]} for r, cols in GOOD.items() if 0 in cols}


def _score(rows):
    ws = _sheet(rows)
    from tests.harness.adapter import adapt
    adapted = adapt([sheet_as_result(ws, _shape())], LABEL, GRID)
    return score_document(LABEL, adapted, doc_text="")


class TestReader:
    def test_reads_fields_and_band_from_a_correct_sheet(self):
        flat = read_sheet(_sheet(GOOD), _shape())
        assert flat["fields"]["Bank Name"] == "First National"
        assert flat["fields"]["Closing Balance"] == 125357.26
        assert len(flat["tables"]["Date"]) == 2

    def test_a_band_stops_at_the_next_labelled_field(self):
        """Reading to the next blank line alone lets the first band swallow the
        rest of the sheet — which is how this reader was wrong at first."""
        flat = read_sheet(_sheet(GOOD), _shape())
        rows = flat["tables"]["Date"]
        assert len(rows) == 2, rows
        assert all("Closing" not in str(r) for r in rows)

    def test_fields_are_found_by_label_not_by_row_number(self):
        """A band that expanded pushes everything below it down; the reader
        must still find the totals row."""
        shifted = {0: GOOD[0], 1: GOOD[1], 3: GOOD[3], 4: GOOD[4], 5: GOOD[5],
                   6: {0: "01/07", 1: 999.0}, 7: {0: "01/08", 1: 111.0},
                   9: GOOD[7]}
        flat = read_sheet(_sheet(shifted), _shape())
        assert flat["fields"]["Closing Balance"] == 125357.26
        assert len(flat["tables"]["Date"]) == 4


class TestItCatchesTheBugItWasBuiltFor:
    def test_a_correct_sheet_scores_full_marks(self):
        assert _score(GOOD)["accuracy"] == 1.0

    def test_labels_written_but_every_value_empty_is_caught(self):
        """The 2026-08-18 export bug, reproduced. Extraction had every value;
        the file had none. Export scoring must see 0%."""
        s = _score(LABELS_ONLY)
        assert s["accuracy"] == 0.0, s["counts"]
        assert s["counts"].get("missed", 0) >= 3

    def test_one_dropped_value_is_caught(self):
        broken = {r: dict(c) for r, c in GOOD.items()}
        del broken[7][1]                       # closing balance missing
        s = _score(broken)
        assert s["accuracy"] < 1.0
        assert s["fields"]["Closing Balance"]["outcome"] == "missed"

    def test_a_value_written_to_the_wrong_cell_is_caught(self):
        broken = {r: dict(c) for r, c in GOOD.items()}
        broken[7][1] = 999.99                  # wrong value in the totals cell
        s = _score(broken)
        assert s["fields"]["Closing Balance"]["outcome"] == "wrong"

    def test_a_dropped_table_row_is_caught(self):
        broken = {r: dict(c) for r, c in GOOD.items() if r != 5}
        s = _score(broken)
        assert s["accuracy"] < 1.0
        assert s["tables"]["Date"]["row_count_mismatch"] == -1
