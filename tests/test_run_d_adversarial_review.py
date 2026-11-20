"""Adversarial, offline review of Run D.

The inputs are editor grids or synthetic page lines only.  No provider, live
model, database, or hosted service is involved.  Strict xfails are real Run D
regressions; passing tests pin the adversarial cases the implementation handles.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from tests.contract import run_a_driver as D
from tests.template_layout.helpers import FIXTURES, scenario_ids, workbook_to_grid

import format_rules as FR  # noqa: E402
import source_inventory as SI  # noqa: E402
from template_shape import compute_shape, is_placeholder, template_warnings  # noqa: E402
from text_layer import watermark_runs  # noqa: E402


def _grid(cells, merges=None):
    return {
        "cells": {f"{r},{c}": {"value": value} for (r, c), value in cells.items()},
        "merges": merges or {},
        "regions": [],
        "colWidths": [],
        "repeatRows": [],
    }


def _shape(grid):
    return compute_shape(grid, log=lambda _message: None)


def _fields(grid):
    return sorted((f["ref"], f["row_label"]) for f in _shape(grid)["field_slots"])


def _bands(grid):
    return [
        (band["name"], tuple(c["header"] for c in band.get("columns") or []))
        for band in _shape(grid)["repeat_bands"]
    ]


def test_d1_two_full_accounts_with_the_same_suffix_are_still_ambiguous():
    lines = D.words(1, ["Account Number 11117421", "Account Number 22227421"])
    assert FR.check_last4("7421", lines, "Account Last 4")[0] == "ambiguous"


def test_d1_the_same_printed_ending_twice_does_not_create_false_ambiguity():
    lines = D.words(1, ["Account ending 7421", "Account ending 7421"])
    assert FR.check_last4("7421", lines, "Account Last 4")[:2] == ("ok", "7421")


def test_d2_routing_cues_and_aba_numbers_do_not_compete_with_the_account():
    lines = D.words(1, [
        "Routing No. 071000505",
        "ABA Number 021000021",
        "Account Number 7301558842",
    ])
    assert FR.account_numbers(lines) == [
        ("7301558842", "Account Number 7301558842")
    ]


def test_d3_oversized_quarter_turn_draft_margin_text_is_kept():
    margin = [
        {"text": char, "size": 48, "matrix": (0, 1, -1, 0)}
        for char in "DRAFT — DO NOT FILE"
    ]
    body = [{"text": "x", "size": 10, "matrix": (1, 0, 0, 1)} for _ in range(20)]
    assert watermark_runs(SimpleNamespace(chars=body + margin)) == []


def test_d4_parenthesized_amounts_are_negative_without_a_less_label():
    rows = {"table": [
        {"Description": "Services", "Amount": "100.00"},
        {"Description": "Refund", "Amount": "($20.00)"},
    ]}
    slots = {"fields": [], "tables": [{"name": "table", "columns": [
        {"header": "Description"}, {"header": "Amount"},
    ]}]}
    page = [D.words(1, ["Services 100.00", "Refund ($20.00)", "Total 80.00"])]
    assert SI.row_sum_checks(slots, rows, page, [1]) == []


def test_d5_a_correct_grand_total_must_not_hide_a_wrong_page_subtotal():
    rows = {"table": [
        {"Description": "A", "Amount": "40.00", "_page": 1},
        {"Description": "B", "Amount": "60.00", "_page": 1},
        {"Description": "C", "Amount": "30.00", "_page": 2},
        {"Description": "D", "Amount": "70.00", "_page": 2},
    ]}
    slots = {"fields": [], "tables": [{"name": "table", "columns": [
        {"header": "Description"}, {"header": "Amount"},
    ]}]}
    pages = [
        D.words(1, ["A 40.00", "B 60.00", "Subtotal 90.00"]),
        D.words(2, ["C 30.00", "D 70.00", "Subtotal 100.00",
                    "Grand Total 200.00"]),
    ]
    assert SI.row_sum_checks(slots, rows, pages, [1, 2]) == [{
        "table": "table", "column": "Amount", "rows": 2,
        "row_sum": "100.00", "printed": ["90.00"], "page": 1,
    }]


def test_d6_blank_rows_really_isolate_scattered_field_groups():
    grid = _grid({
        (0, 0): "Entity", (0, 2): "Period", (0, 7): "Status",
        (3, 0): "Owner", (3, 2): "Region", (3, 4): "Currency",
        (3, 6): "Rate", (3, 8): "Threshold", (4, 6): "Reviewer",
    })
    assert _fields(grid) == sorted([
        ("B1", "Entity"), ("D1", "Period"), ("I1", "Status"),
        ("B4", "Owner"), ("D4", "Region"), ("F4", "Currency"),
        ("H4", "Rate"), ("J4", "Threshold"), ("H5", "Reviewer"),
    ])


def test_d6_a_matrix_heading_may_have_one_intentionally_empty_cell():
    # A real two-value comparison: A names the rows, B is the unlabeled current
    # amount, and C is the explicitly headed prior-year amount.
    grid = _grid({
        (0, 0): "Line item", (0, 2): "2026",
        (1, 0): "Revenue", (2, 0): "Expenses",
    })
    assert _fields(grid) == [
        ("B2", "Revenue"), ("B3", "Expenses"),
        ("C2", "Revenue"), ("C3", "Expenses"),
    ]


def test_d7_a_blank_spacer_inside_one_table_does_not_make_two_tables():
    grid = _grid({
        (0, 0): "Date", (0, 1): "Description",
        (0, 3): "Debit", (0, 4): "Balance",
        (5, 0): "Total",
    })
    assert _bands(grid) == [
        ("table", ("Date", "Description", "Debit", "Balance")),
    ]


def test_d8_a_note_beside_a_table_is_not_a_scalar_field():
    grid = _grid({
        (0, 0): "Date", (0, 1): "Description", (0, 2): "Amount",
        (1, 4): "Amounts in USD", (5, 0): "Total",
    })
    assert _fields(grid) == [("B6", "Total")]


def test_d9_below_is_used_only_when_the_right_cell_is_not_usable():
    right = _grid({(0, 0): "Name", (0, 2): "Date", (2, 0): "Notes"})
    blocked = _grid({
        (0, 0): "Approver", (0, 1): "Title", (1, 1): "Dept",
        (2, 0): "Phone", (2, 1): "Ext",
    })
    assert ("B1", "Name") in _fields(right)
    assert ("A2", "Name") not in _fields(right)
    assert ("A2", "Approver") in _fields(blocked)


def test_d10_a_merged_section_heading_does_not_own_a_decorative_empty_merge():
    grid = _grid(
        {(0, 0): "Invoice Summary", (2, 0): "Total"},
        merges={
            "0,0": {"rows": 1, "cols": 2},
            "0,2": {"rows": 1, "cols": 2},
        },
    )
    assert _fields(grid) == [("B3", "Total")]


def test_d11_total_due_tbd_is_a_legitimate_label_not_a_placeholder():
    assert not is_placeholder("Total due TBD")
    assert _fields(_grid({(0, 0): "Total due TBD", (1, 0): "Approval"})) == [
        ("B1", "Total due TBD"), ("B2", "Approval"),
    ]


def test_d11_an_exact_tbd_label_can_be_real_template_text():
    grid = _grid({(0, 0): "TBD", (1, 0): "Approval"})
    assert _fields(grid) == [("B1", "TBD"), ("B2", "Approval")]


def test_d12_a_vertical_merge_over_a_scalar_label_is_not_a_table_header():
    grid = _grid(
        {(0, 0): "Customer", (1, 1): "Invoice Date", (3, 0): "Total"},
        merges={"0,0": {"rows": 2, "cols": 1}},
    )
    assert _bands(grid) == []
    assert _fields(grid) == [
        ("B1", "Customer"), ("B4", "Total"), ("C2", "Invoice Date"),
    ]


def test_d13_owner_approved_header_only_tables_do_not_need_a_warning():
    grid = _grid({(0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount"})
    assert template_warnings(grid) == []


def test_d13_a_valid_horizontal_field_pair_is_not_warning_noise():
    grid = _grid({(0, 0): "Name", (2, 0): "Notes"})
    assert _fields(grid) == [("B1", "Name"), ("B3", "Notes")]
    assert template_warnings(grid) == []


def _committed_template_grids():
    for scenario in scenario_ids():
        yield f"scenario/{scenario}", workbook_to_grid(FIXTURES / f"{scenario}.xlsx")

    repo = Path(__file__).resolve().parents[1]
    acceptance = repo / "tests/fixtures/acceptance/templates/DocAgent_templates_v2.xlsx"
    workbook = openpyxl.load_workbook(acceptance, data_only=False)
    for sheet in workbook.sheetnames:
        yield f"acceptance/{sheet}", workbook_to_grid(acceptance, sheet)

    for path in sorted((repo / "tests/fixtures/prod_templates").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        yield f"prod/{path.stem}", data["grid"]
    for path in sorted((repo / "tests/gold/templates").glob("*.json")):
        yield f"gold/{path.stem}", json.loads(path.read_text(encoding="utf-8"))
    for path in sorted((repo / "tests/fixtures/round2_templates").glob("*.json")):
        yield f"round2/{path.stem}", json.loads(path.read_text(encoding="utf-8"))


def test_d13_warning_inventory_is_reproducible_over_every_committed_template():
    grids = list(_committed_template_grids())
    warnings = {name: template_warnings(grid) for name, grid in grids}
    warned = {name: items for name, items in warnings.items() if items}
    assert len(grids) == 96
    # Run E, E8: was 33 grids / 36 warnings, 33 of them noise on valid
    # layouts. What remains is F10's two formula cells.
    assert len(warned) == 1
    assert sum(map(len, warned.values())) == 2

