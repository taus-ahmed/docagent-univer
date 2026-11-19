"""Run B, B6 - row sum against the printed total (flag only)."""
from __future__ import annotations

import json

from tests.contract.run_a_driver import model_response, run_synthetic, words

import source_inventory as SI  # noqa: E402

SLOTS = {"fields": [], "tables": [{"name": "table", "columns": [
    {"header": "Date"}, {"header": "Description"}, {"header": "Amount"}]}]}
ROWS = {"table": [{"Date": "01/01", "Description": "ITEM-A", "Amount": "40.00"},
                  {"Date": "01/02", "Description": "ITEM-B", "Amount": "60.00"}]}


def _checks(lines):
    return SI.row_sum_checks(SLOTS, ROWS, [words(1, lines)], [1])


def test_a_matching_total_says_nothing():
    assert _checks(["DATE DESCRIPTION AMOUNT", "01/01 ITEM-A 40.00",
                    "01/02 ITEM-B 60.00", "Total 100.00"]) == []


def test_subtotal_tax_total_is_consistent_by_its_subtotal():
    assert _checks(["01/01 ITEM-A 40.00", "01/02 ITEM-B 60.00",
                    "Subtotal 100.00", "Tax 8.00", "Total 108.00"]) == []


def test_a_mismatch_is_reported_with_both_numbers():
    out = _checks(["01/01 ITEM-A 40.00", "01/02 ITEM-B 60.00", "Total 110.00"])
    assert out == [{"table": "table", "column": "Amount", "rows": 2,
                    "row_sum": "100.00", "printed": ["110.00"]}]


def test_no_printed_total_no_verdict_and_a_running_balance_is_not_summed():
    assert _checks(["01/01 ITEM-A 40.00", "01/02 ITEM-B 60.00"]) == []
    slots = {"fields": [], "tables": [{"name": "t", "columns": [
        {"header": "Description"}, {"header": "Running Balance"}]}]}
    rows = {"t": [{"Description": "A", "Running Balance": "10.00"},
                  {"Description": "B", "Running Balance": "30.00"}]}
    assert SI.row_sum_checks(slots, rows, [words(1, ["Total 99.00"])], [1]) == []


def test_the_total_cell_is_flagged_and_no_row_is_changed():
    grid = {"cells": {"0,0": {"value": "Date"}, "0,1": {"value": "Description"},
                      "0,2": {"value": "Amount"}, "8,0": {"value": "Total"}},
            "merges": {}, "colWidths": [], "repeatRows": []}
    from slot_extractor import enumerate_slots
    slots = enumerate_slots(grid)
    total_id = next(f["slot_id"] for f in slots["fields"] if f["row_label"] == "Total")
    answer = {"fields": {total_id: {"value": "110.00", "source": "Total 110.00", "page": 1}},
              "tables": {slots["tables"][0]["name"]: [
                  {"cells": {"Date": "01/01", "Description": "ITEM-A", "Amount": "40.00"},
                   "source": "01/01 ITEM-A 40.00", "page": 1},
                  {"cells": {"Date": "01/02", "Description": "ITEM-B", "Amount": "60.00"},
                   "source": "01/02 ITEM-B 60.00", "page": 1}]}}
    data = run_synthetic(lambda **kw: model_response(json.loads(json.dumps(answer))),
                         [["DATE DESCRIPTION AMOUNT", "01/01 ITEM-A 40.00",
                           "01/02 ITEM-B 60.00", "Total 110.00"]], grid=grid)
    flags = [f for f in data["validation"]["flagged_fields"] if f["ref"] == "Total"]
    assert flags and "sum to 100.00" in flags[0]["reason"] and "110.00" in flags[0]["reason"]
    rows = data["table_rows"] or next(v for k, v in data.items() if k.endswith("_rows"))
    assert [r["Amount"] for r in rows] == ["40.00", "60.00"]
    assert data["extracted_data"]["Total"]["value"] == "110.00"
