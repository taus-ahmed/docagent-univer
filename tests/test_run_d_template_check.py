"""Run D, D13 — the template check: plain-language warnings about regions the
engine may misread. Information only; nothing here blocks a save."""
from __future__ import annotations

from tests.harness import bootstrap as bs

bs.bootstrap()

from template_shape import template_warnings  # noqa: E402


def _grid(cells, merges=None):
    return {"cells": {f"{r},{c}": {"value": v} for (r, c), v in cells.items()},
            "merges": merges or {}, "colWidths": [], "repeatRows": []}


def _has(warnings, *words):
    return any(all(w in x for w in words) for x in warnings)


def test_a_formula_is_said_to_be_read_as_a_label():
    w = template_warnings(_grid({(0, 0): "Net", (0, 2): "=SUM(B1:B3)"}))
    assert _has(w, "C1", "=SUM(B1:B3)", "formula", "label")


def test_two_tables_sharing_rows_are_a_valid_layout_and_say_nothing():
    """Run E, E8 (D13): side-by-side tables grow by the larger — the design,
    not a misreading. This test used to require a warning here."""
    w = template_warnings(_grid({
        (0, 0): "A1", (0, 1): "A2", (0, 2): "A3",
        (0, 4): "B1", (0, 5): "B2", (0, 6): "B3", (4, 0): "Total"}))
    assert w == []


def test_a_label_with_an_implied_right_slot_and_an_empty_cell_below_is_valid():
    """E8 (D13): a usable right cell is authoritative (owner ruling, F2), so
    there is nothing ambiguous to warn about. It used to warn."""
    w = template_warnings(_grid({(0, 0): "Name", (2, 0): "Notes"}))
    assert w == []


def test_an_empty_merged_box_no_label_points_at():
    w = template_warnings(_grid({(0, 0): "Name", (2, 0): "Notes"},
                                merges={"0,3": {"rows": 1, "cols": 2}}))
    assert _has(w, "D1:E1", "no label points at it")


def test_a_header_with_no_empty_rows_beneath_is_valid():
    """E8 (D13): the owner-approved header-only shape (ten reserved rows).
    It used to warn."""
    w = template_warnings(_grid({(0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount"}))
    assert w == []


def test_a_one_row_merge_inside_a_table_is_recreated_and_says_nothing():
    """E8: since E4 a one-row merge in a table's body is written on every
    record row, so the old "not recreated" warning would be false."""
    w = template_warnings(_grid({(0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount",
                                 (6, 0): "Total"},
                                merges={"2,0": {"rows": 1, "cols": 2}}))
    assert w == []


def test_a_merge_over_several_table_rows_still_warns():
    w = template_warnings(_grid({(0, 0): "Item", (0, 1): "Qty", (0, 2): "Amount",
                                 (6, 0): "Total"},
                                merges={"2,0": {"rows": 2, "cols": 2}}))
    assert _has(w, "A3:B4", "covers rows of table")


def test_a_subtotal_formula_inside_a_table_says_nothing():
    w = template_warnings(_grid({(0, 0): "Item", (0, 1): "Date", (0, 2): "Qty",
                                 (0, 3): "Rate", (0, 4): "Amount",
                                 (3, 0): "Subtotal", (3, 4): "=SUM(E2:E3)",
                                 (6, 0): "Total"}))
    assert w == []


def test_an_ordinary_template_says_nothing():
    w = template_warnings(_grid({(0, 0): "Name", (1, 0): "Date",
                                 (3, 0): "Item", (3, 1): "Qty", (3, 2): "Amount",
                                 (8, 0): "Total"}))
    assert w == []
