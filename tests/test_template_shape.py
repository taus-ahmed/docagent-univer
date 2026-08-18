"""
Unit tests for template shape (Phase 2a). Offline, always green.

The shape is now the single description of a template's structure, so the one
rule it encodes — text = static label, empty = slot — is tested directly,
including the case the old `extractTarget` marker created: a cell that claimed
to be both.
"""
import json

from tests.harness import bootstrap as bs

bs.bootstrap()

from template_shape import compute_shape, describe, is_usable  # noqa: E402


def _grid(cells, marks=None):
    marks = marks or {}
    return {"cells": {k: {"value": v, "extractTarget": marks.get(k, False)}
                      for k, v in cells.items()}}


class TestTheOneRule:
    def test_text_is_a_label_empty_is_a_slot(self):
        s = compute_shape(_grid({"0,0": "Bank Name", "0,1": ""}))
        assert [f["row_label"] for f in s["field_slots"]] == ["Bank Name"]
        assert s["field_slots"][0]["ref"] == "B1"

    def test_extract_target_marker_no_longer_decides_anything(self):
        """The marker used to be a second, independent way to say 'slot'. A
        cell marked extractable that CONTAINS text is a contradiction the old
        model had no answer for; under the one rule the text wins."""
        marked = _grid({"0,0": "Total", "0,1": "999"}, marks={"0,1": True})
        plain = _grid({"0,0": "Total", "0,1": "999"})
        assert compute_shape(marked)["field_slots"] == compute_shape(plain)["field_slots"]
        assert compute_shape(marked)["field_slots"] == []   # both cells are labels

    def test_marker_on_an_empty_cell_changes_nothing_either(self):
        marked = _grid({"0,0": "Total", "0,1": ""}, marks={"0,1": True})
        plain = _grid({"0,0": "Total", "0,1": ""})
        assert compute_shape(marked)["field_slots"] == compute_shape(plain)["field_slots"]

    def test_contradictory_markers_are_counted_for_migration(self):
        s = compute_shape(_grid({"0,0": "Total", "0,1": "999"}, marks={"0,1": True}))
        assert s["migration"]["extract_target_cells"] == 1
        assert s["migration"]["extract_target_cells_with_text"] == 1


class TestBands:
    def test_header_row_over_empty_rows_is_a_repeating_band(self):
        s = compute_shape(_grid({"0,0": "Date", "0,1": "Amount",
                                 "4,0": "Total", "4,1": ""}))
        assert len(s["repeat_bands"]) == 1
        b = s["repeat_bands"][0]
        assert [c["header"] for c in b["columns"]] == ["Date", "Amount"]
        assert (b["start_row"], b["end_row"]) == (1, 3)

    def test_stacked_labels_are_not_a_band(self):
        s = compute_shape(_grid({"0,0": "Vendor", "0,1": "Acme",
                                 "1,0": "Buyer", "1,1": "Nexus"}))
        assert s["repeat_bands"] == []

    def test_totals_row_below_a_band_is_a_field_not_a_band_row(self):
        s = compute_shape(_grid({"0,0": "Date", "0,1": "Amount",
                                 "4,0": "Total", "4,1": ""}))
        assert [f["row_label"] for f in s["field_slots"]] == ["Total"]


class TestRequiredColumns:
    """required_columns is what Phase 2b's router does arithmetic on."""

    def test_widest_band_sets_the_requirement(self):
        s = compute_shape(_grid({"0,0": "Date", "0,1": "Type", "0,2": "Debit",
                                 "0,3": "Credit", "6,0": "Total", "6,1": ""}))
        assert s["required_columns"] == 4

    def test_kv_only_template_needs_two(self):
        s = compute_shape(_grid({"0,0": "Payee", "0,1": ""}))
        assert s["required_columns"] == 2

    def test_empty_template_needs_none(self):
        s = compute_shape({"cells": {}})
        assert s["required_columns"] == 0
        assert is_usable(s) is False


class TestRealTemplates:
    def test_every_gold_template_yields_a_usable_shape(self):
        for f in sorted(bs.TEMPLATES_DIR.glob("*.json")):
            shape = compute_shape(json.loads(f.read_text(encoding="utf-8")))
            assert is_usable(shape), f.name
            assert shape["summary"], f.name

    def test_bank_statement_shape(self):
        grid = json.loads((bs.TEMPLATES_DIR / "bank_statement.json").read_text())
        s = compute_shape(grid)
        assert len(s["field_slots"]) == 10
        assert s["required_columns"] == 6
        b = s["repeat_bands"][0]
        assert [c["header"] for c in b["columns"]] == [
            "Date", "Type", "Description", "Debit", "Credit", "Balance"]
        assert (b["start_row"], b["end_row"]) == (10, 21)

    def test_summary_is_produced_server_side(self):
        """The frontend displays this string rather than re-deriving the rule
        in TypeScript, so there is exactly one implementation of it."""
        s = compute_shape(_grid({"0,0": "Payee", "0,1": ""}))
        assert describe(s) == s["summary"]
        assert "field slots" in s["summary"]


class TestRobustness:
    def test_garbage_grid_does_not_raise(self):
        for bad in [None, {}, {"cells": None}, {"cells": {"x": "y"}},
                    {"cells": {"1,2,3": {"value": "a"}}}]:
            s = compute_shape(bad)
            assert s["required_columns"] == 0
