"""Independent, offline adversarial review of the Run E template fixes.

The inputs are committed editor grids or tiny synthetic grids.  No model,
database, source document, or remote service is used.
"""
from __future__ import annotations

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from slot_extractor import enumerate_slots  # noqa: E402
from template_shape import compute_shape, template_warnings  # noqa: E402
from tests.contract.run_a_driver import template_grid  # noqa: E402
from tests.template_layout.helpers import shape_for  # noqa: E402


def _grid(cells):
    return {
        "cells": {f"{row},{col}": {"value": value}
                  for (row, col), value in cells.items()},
        "merges": {},
        "regions": [],
        "colWidths": [],
        "repeatRows": [],
    }


def _fields(grid):
    shape = compute_shape(grid, log=lambda _message: None)
    return sorted((field["ref"], field["row_label"])
                  for field in shape["field_slots"])


def _band_headers(grid):
    shape = compute_shape(grid, log=lambda _message: None)
    return [tuple(column["header"] for column in band["columns"])
            for band in shape["repeat_bands"]]


def test_e1_ap_invoice_keeps_its_subtotal_tax_and_total_slots():
    """The Run E table-end refinement must not regress C4's owner invoice."""
    slots = enumerate_slots(template_grid("AP_Inv_Full"))
    labels = {field["row_label"] for field in slots["fields"]}
    assert {"Subtotal", "Tax Total", "Invoice Total"} <= labels
    assert slots["tables"][0]["end_row"] == 33


def test_e8_right_slot_with_an_empty_cell_below_is_intentionally_silent():
    grid = _grid({(0, 0): "Name", (2, 0): "Notes"})
    assert _fields(grid) == [("B1", "Name"), ("B3", "Notes")]
    assert template_warnings(grid) == []


def test_e8_t14_native_table_metadata_is_invisible_and_therefore_silent():
    grid, _shape = shape_for("T14")
    assert template_warnings(grid) == []


def test_d6_a_numbered_form_label_is_not_a_matrix_year_heading():
    grid = _grid({
        (0, 0): "Name", (0, 2): "Approver 2",
        (1, 0): "Address",
    })
    assert _fields(grid) == [
        ("B1", "Name"), ("B2", "Address"), ("D1", "Approver 2"),
    ]


def test_d8_a_note_beside_a_table_may_contain_the_word_total():
    grid = _grid({
        (0, 0): "Date", (0, 1): "Description", (0, 2): "Amount",
        (1, 4): "Total amounts shown in USD",
        (5, 0): "Total",
    })
    assert _fields(grid) == [("B6", "Total")]


def test_d7_two_tables_stay_separate_when_one_is_two_columns_wide():
    grid = _grid({
        (0, 0): "Code", (0, 1): "Amount",
        (0, 3): "Date", (0, 4): "Description", (0, 5): "Charge",
        (4, 0): "Left total", (4, 3): "Right total",
    })
    assert _band_headers(grid) == [
        ("Code", "Amount"),
        ("Date", "Description", "Charge"),
    ]
