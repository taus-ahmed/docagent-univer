"""
The editor's slot highlighting must show exactly what will be extracted.

Highlighting every empty cell inside the bounding box painted a wall of green:
one template showed 54 slots where about 15 were intended, because a single
label parked in column G stretched the box across everything to its left. The
user could not tell intent from accident.

The rule is unchanged — a cell is a slot only beside a static label or inside a
detected band — and it still lives in one place, `template_shape.compute_shape`.
`POST /api/templates/shape` exposes it so the editor can highlight the engine's
answer instead of re-deriving one of its own.
"""
from tests.harness import bootstrap as bs

bs.bootstrap()

from app.api.routes.templates import preview_shape  # noqa: E402


def _grid(cells, cols=8, rows=15, fill_empties=True):
    g = {f"{r},{c}": {"value": "", "style": {}}
         for r in range(rows) for c in range(cols)} if fill_empties else {}
    for k, v in cells.items():
        g[k] = {"value": v, "style": {}}
    return {"cells": g, "colWidths": [140] * cols, "merges": {}, "repeatRows": []}


def _preview(grid):
    return preview_shape({"grid": grid}, current_user=None)


# The reported template: four labelled fields, a five-column band, and a
# "Total Claimed" label out in column G that stretches the bounding box.
REPORTED = {}
for _i, _l in enumerate(["Employee", "Employee ID", "Department", "Period"]):
    REPORTED[f"{_i},0"] = _l
for _c, _h in enumerate(["Date", "Type", "Description", "Category", "Amount"]):
    REPORTED[f"6,{_c}"] = _h
REPORTED["14,6"] = "Total Claimed"


class TestOnlyRealSlotsAreReported:
    def test_the_wall_of_green_is_gone(self):
        grid = _grid(REPORTED)
        empties = sum(1 for c in grid["cells"].values() if not c["value"])
        d = _preview(grid)
        highlighted = d["field_count"] + d["band_count"]
        assert empties > 100, empties
        assert highlighted < empties / 2, (highlighted, empties)

    def test_a_field_slot_is_the_cell_beside_a_label(self):
        d = _preview(_grid(REPORTED))
        for ref in ["0,1", "1,1", "2,1", "3,1"]:
            assert ref in d["field_cells"], (ref, d["field_cells"])

    def test_a_label_far_to_the_right_still_gets_its_own_slot(self):
        """'Total Claimed' in column G is a real field — it must be a slot,
        just not a reason to light up every cell to its left."""
        assert "14,7" in _preview(_grid(REPORTED))["field_cells"]

    def test_cells_that_are_merely_empty_are_not_slots(self):
        d = _preview(_grid(REPORTED))
        every = set(d["field_cells"]) | set(d["band_cells"])
        for ref in ["0,4", "1,5", "2,6", "3,7", "5,3", "13,6"]:
            assert ref not in every, ref

    def test_the_band_is_reported_with_its_columns(self):
        d = _preview(_grid(REPORTED))
        assert len(d["bands"]) == 1
        b = d["bands"][0]
        assert b["columns"] == ["Date", "Type", "Description", "Category", "Amount"]
        assert b["header_row"] == 6
        assert d["band_count"] == (b["end_row"] - b["start_row"] + 1) * 5

    def test_every_band_cell_is_inside_the_band(self):
        d = _preview(_grid(REPORTED))
        b = d["bands"][0]
        for ref in d["band_cells"]:
            r, c = map(int, ref.split(","))
            assert b["start_row"] <= r <= b["end_row"], ref
            assert 0 <= c < 5, ref


class TestItMatchesWhatIsExtracted:
    def test_the_highlighted_cells_are_the_shape_the_engine_uses(self):
        """The point of asking the server: the highlight and the extraction
        come from the same call, so they cannot disagree."""
        from template_shape import compute_shape
        grid = _grid(REPORTED)
        d = _preview(grid)
        shape = compute_shape(grid)
        assert d["field_count"] == len(shape["field_slots"])
        assert {f"{f['row']},{f['col']}" for f in shape["field_slots"]} == \
            set(d["field_cells"])
        assert d["required_columns"] == shape["required_columns"]


class TestRobustness:
    def test_a_non_grid_payload_is_refused_not_crashed(self):
        for bad in [{}, {"grid": None}, {"grid": "nonsense"}, {"grid": {"x": 1}}]:
            d = preview_shape(bad, current_user=None)
            assert d["field_count"] == 0 and d["band_count"] == 0

    def test_a_grid_as_a_json_string_is_accepted(self):
        import json
        d = preview_shape({"grid": json.dumps(_grid(REPORTED))}, current_user=None)
        assert d["field_count"] > 0

    def test_an_empty_grid_reports_nothing(self):
        d = _preview({"cells": {}, "colWidths": [], "merges": {}, "repeatRows": []})
        assert d["field_count"] == 0 and d["band_count"] == 0
