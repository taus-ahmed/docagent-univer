"""Run D — template shape rules not covered by an audit scenario of their own."""
from __future__ import annotations

from tests.harness import bootstrap as bs

bs.bootstrap()

from template_shape import compute_shape  # noqa: E402


def _grid(cells, merges=None):
    return {"cells": {f"{r},{c}": {"value": v} for (r, c), v in cells.items()},
            "merges": merges or {}, "colWidths": [], "repeatRows": []}


def _fields(grid):
    return sorted((f["ref"], f["row_label"])
                  for f in compute_shape(grid, log=lambda _m: None)["field_slots"])


class TestD9LabelAboveValue:
    def test_a_label_with_a_label_to_its_right_takes_the_cell_below(self):
        g = _grid({(0, 0): "Approver", (0, 1): "Title", (1, 1): "Dept",
                   (2, 0): "Phone", (2, 1): "Ext"})
        assert ("A2", "Approver") in _fields(g)

    def test_when_the_right_cell_is_usable_it_wins_and_below_is_not_guessed(self):
        g = _grid({(0, 0): "Name", (0, 2): "Date", (2, 0): "Notes"})
        got = _fields(g)
        assert ("B1", "Name") in got and ("A2", "Name") not in got

    def test_a_heading_merged_across_columns_never_takes_a_slot_below(self):
        g = _grid({(0, 0): "Section heading", (2, 0): "Total"},
                  merges={"0,0": {"rows": 1, "cols": 2}})
        assert not [f for f in _fields(g) if f[1] == "Section heading"]


class TestD6ScatteredGroups:
    def test_the_owner_example(self):
        """Row 1: fields in columns 1-3 and 8-9; row 4 with five; row 5 with
        only columns 7-8 (the owner's own description)."""
        g = _grid({(0, 0): "Entity", (0, 2): "Period", (0, 7): "Status",
                   (3, 0): "Owner", (3, 2): "Region", (3, 4): "Currency",
                   (3, 6): "Rate", (3, 8): "Threshold", (4, 6): "Reviewer"})
        assert _fields(g) == sorted([
            ("B1", "Entity"), ("D1", "Period"), ("I1", "Status"),
            ("B4", "Owner"), ("D4", "Region"), ("F4", "Currency"),
            ("H4", "Rate"), ("J4", "Threshold"), ("H5", "Reviewer")])
