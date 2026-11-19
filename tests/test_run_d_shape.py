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


class TestD11Placeholders:
    import pytest as _pt

    @_pt.mark.parametrize("text", ["enter here", "Enter value here", "____", "[ ]",
                                   "[enter name]", "{{ }}", "{{amount}}", "xxx",
                                   "XXXX", "TBD", "....", "---"])
    def test_a_placeholder_is_an_empty_slot(self, text):
        from template_shape import is_placeholder
        assert is_placeholder(text)
        assert _fields(_grid({(0, 0): "Name", (0, 1): text})) == [("B1", "Name")]

    @_pt.mark.parametrize("text", ["Notes [optional]", "XX-100", "Enter Date",
                                   "Total", "N/A", "x"])
    def test_ordinary_text_is_not_a_placeholder(self, text):
        from template_shape import is_placeholder
        assert not is_placeholder(text)

    def test_the_writer_replaces_a_placeholder_and_never_copies_it(self):
        import io
        import contextlib
        import json
        import openpyxl
        from types import SimpleNamespace
        from slot_extractor import enumerate_slots
        from app.api.routes.extract import _write_slot_excel
        g = _grid({(0, 0): "Name", (0, 1): "[enter name]",
                   (1, 0): "Date", (1, 1): "TBD"})
        slots = enumerate_slots(g)
        refs = {f["row_label"]: f["ref"] for f in slots["fields"]}
        ed = {"template_type": "slot", "extracted_fields": {refs["Name"]: "Ada"},
              "slot_map": {"fields": slots["fields"], "tables": []},
              "validation": {"confidence_map": {}, "flagged_fields": []}}
        s = json.dumps(ed)
        doc = SimpleNamespace(filename="x.pdf", get_extracted_data=lambda: json.loads(s))
        wb = openpyxl.Workbook()
        with contextlib.redirect_stdout(io.StringIO()):
            _write_slot_excel(wb.active, [doc], g, g["cells"], openpyxl)
        ws = wb.active
        assert ws["B1"].value == "Ada" and ws["B2"].value is None


class TestD12InteriorRows:
    """T11's behaviour (its own write test also asks for one cell to hold a
    record and the subtotal formula at once, so it stays xfail): a subtotal
    row drawn inside a table keeps its place and records go around it."""

    def _write(self, n):
        import io
        import contextlib
        import json
        import openpyxl
        from types import SimpleNamespace
        from slot_extractor import _table_map, enumerate_slots
        from app.api.routes.extract import _write_slot_excel
        g = _grid({(0, 0): "Item", (0, 1): "Date", (0, 2): "Qty", (0, 3): "Rate",
                   (0, 4): "Amount", (3, 0): "Subtotal", (3, 4): "=SUM(E2:E3)",
                   (6, 0): "Total"})
        slots = enumerate_slots(g)
        t = slots["tables"][0]
        assert (t["start_row"], t["end_row"]) == (1, 5), t
        ed = {"template_type": "slot", "extracted_fields": {},
              "slot_map": {"fields": slots["fields"],
                           "tables": [_table_map(t) for t in slots["tables"]]},
              "validation": {"confidence_map": {}, "flagged_fields": []},
              f"{t['name']}_rows": [{"Item": f"I{k}", "Amount": f"{k}.00"} for k in range(n)]}
        s = json.dumps(ed)
        doc = SimpleNamespace(filename="x.pdf", get_extracted_data=lambda: json.loads(s))
        wb = openpyxl.Workbook()
        with contextlib.redirect_stdout(io.StringIO()):
            _write_slot_excel(wb.active, [doc], g, g["cells"], openpyxl)
        ws = wb.active
        return [ws.cell(r, 1).value for r in range(1, ws.max_row + 1)], ws

    def test_records_fill_around_the_subtotal_row(self):
        col_a, ws = self._write(4)
        assert col_a[:7] == ["Item", "I0", "I1", "Subtotal", "I2", "I3", "Total"]
        assert ws["E4"].value == "=SUM(E2:E3)"

    def test_unused_free_rows_are_dropped_and_extra_records_follow(self):
        assert self._write(1)[0][:4] == ["Item", "I0", "Subtotal", "Total"]
        assert self._write(6)[0][:9] == ["Item", "I0", "I1", "Subtotal", "I2", "I3",
                                         "I4", "I5", "Total"]
