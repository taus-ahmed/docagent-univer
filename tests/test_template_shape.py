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


# ══════════════════════════════════════════════════════════════════════════════
# R1 — THE USED RANGE IS DENSE
# ══════════════════════════════════════════════════════════════════════════════
#
# A cell the user never touched and a cell they touched and left empty are the
# same thing to a template. They were not the same thing to `_matrix`, which
# read `grid["cells"]` and so could only see cells the React editor happened to
# serialise — it writes an entry when you type, style, merge or paste, and
# never when you leave a cell alone. Drawing a border was therefore what made a
# template extractable, and the most ordinary template anyone draws (a column
# of labels) scored zero slots.


def _drawn(cells, regions=None, merges=None):
    """A grid holding ONLY the cells named — exactly what the editor saves."""
    return {"cells": {k: {"value": v} for k, v in cells.items()},
            "colWidths": [], "merges": merges or {}, "repeatRows": [],
            "regions": regions or []}


class TestAColumnOfLabelsIsATemplate:
    """Case 1: labels down column A and nothing else."""

    def test_it_has_a_slot_for_every_label(self):
        g = _drawn({f"{r},0": n for r, n in
                   enumerate(["Name", "Date", "Total", "Tax", "Net"])})
        shape = compute_shape(g)
        assert [f["ref"] for f in shape["field_slots"]] == [
            "B1", "B2", "B3", "B4", "B5"]

    def test_it_is_usable(self):
        g = _drawn({"0,0": "Invoice Number", "1,0": "Total"})
        assert is_usable(compute_shape(g))


class TestStylingIsNotWhatMakesATemplateValid:
    """Case 3: borders used to be an undocumented second path to validity.

    `applyStyle` writes `{value: "", style: {...}}` for every cell in the
    selection, so a bordered empty cell became "present and empty" — a slot —
    while the identical unbordered cell did not exist at all. Two templates
    that look the same on screen extracted differently.
    """

    def test_a_bordered_grid_and_a_bare_one_have_the_same_shape(self):
        labels = {"0,0": "Headings", "0,1": "Value",
                  "1,0": "Name", "2,0": "Date", "3,0": "Total"}
        bare = compute_shape(_drawn(labels))

        bordered = {k: {"value": v} for k, v in labels.items()}
        for r in range(1, 4):                       # user dragged a border box
            bordered[f"{r},1"] = {"value": "", "style": {"borderAll": True}}
        drawn = compute_shape({"cells": bordered, "merges": {}, "regions": []})

        assert [f["ref"] for f in bare["field_slots"]] == \
               [f["ref"] for f in drawn["field_slots"]]


class TestTheUsedRangeStopsAtTheContent:
    """The box comes from TEXT, so styling cannot inflate it."""

    def test_a_lone_label_does_not_mint_a_whole_sheet_of_slots(self):
        shape = compute_shape(_drawn({"0,0": "Invoice Number"}))
        assert len(shape["field_slots"]) == 1

    def test_a_five_column_table_gains_no_sixth_column(self):
        cells = {f"0,{i}": h for i, h in
                 enumerate(["Date", "Item", "Qty", "Rate", "Amount"])}
        cells["6,0"] = "Total"
        shape = compute_shape(_drawn(cells))
        for band in shape["repeat_bands"]:
            assert len(band["columns"]) == 5, band
        assert all(f["col"] <= 4 for f in shape["field_slots"])


# ══════════════════════════════════════════════════════════════════════════════
# R4 — MERGES ARE READ FROM THE RANGE LIST
# ══════════════════════════════════════════════════════════════════════════════


class TestAMergedHeadingIsNotAField:
    """A heading spanning A1:E1 is a title, not a label with a value beside it.

    `mergeCells` writes `{value: "", mergeParent: [r, c]}` into every covered
    cell. Nothing read merges, so B1 looked like an ordinary empty neighbour
    and became a slot labelled with the heading text — and the row then held
    five cells rather than one, so the heading was not recognised as a section
    and the table below it lost its name.
    """

    @staticmethod
    def _merged_heading_grid():
        cells = {"0,0": {"value": "QUARTERLY SUMMARY"}}
        for c in range(1, 5):
            cells[f"0,{c}"] = {"value": "", "mergeParent": [0, 0]}
        for i, h in enumerate(["Date", "Description", "Debit",
                               "Credit", "Balance"]):
            cells[f"2,{i}"] = {"value": h}
        return {"cells": cells, "merges": {"0,0": {"rows": 1, "cols": 5}},
                "regions": []}

    def test_the_heading_does_not_become_a_slot(self):
        shape = compute_shape(self._merged_heading_grid())
        assert shape["field_slots"] == [], shape["field_slots"]

    def test_the_table_beneath_it_takes_its_name(self):
        shape = compute_shape(self._merged_heading_grid())
        assert [b["name"] for b in shape["repeat_bands"]] == [
            "QUARTERLY SUMMARY"]

    def test_the_top_level_merge_list_alone_is_enough(self):
        """The editor is inconsistent about writing `mergeParent`.

        In the committed `bank_statement_101` fixture the merge at "1,0" has
        no `mergeParent` on its covered cells while the one at "6,0" does.
        `grid["merges"]` is the authority; `mergeParent` is only read so grids
        saved by older editors still resolve.
        """
        cells = {"0,0": {"value": "QUARTERLY SUMMARY"}}
        for i, h in enumerate(["Date", "Description", "Debit",
                               "Credit", "Balance"]):
            cells[f"2,{i}"] = {"value": h}
        shape = compute_shape({"cells": cells,
                               "merges": {"0,0": {"rows": 1, "cols": 5}},
                               "regions": []})
        assert shape["field_slots"] == []
        assert [b["name"] for b in shape["repeat_bands"]] == [
            "QUARTERLY SUMMARY"]


class TestSectionTitlesSurviveADenseGrid:
    """A title sits on the line directly above the thing it titles.

    Section detection used to require the title's row to hold exactly one cell
    IN THE GRID — the same editor-bookkeeping artefact R1 removes. Under a
    dense used range every row has a cell in every column, so the balance
    sheet's bands would have been named after the running totals above them.
    """

    def test_a_title_against_its_header_names_the_band(self):
        cells = {"0,0": "Earnings", "1,0": "Description", "1,1": "Amount",
                 "4,0": "Total Earnings"}
        shape = compute_shape(_drawn(cells))
        assert [b["name"] for b in shape["repeat_bands"]] == ["Earnings"]

    def test_a_total_a_blank_line_above_a_header_does_not(self):
        cells = {"0,0": "Total Current Assets",
                 "2,0": "NON-CURRENT ASSETS", "2,1": "Amount",
                 "5,0": "Total Non-Current Assets"}
        shape = compute_shape(_drawn(cells))
        assert [b["name"] for b in shape["repeat_bands"]] == [
            "NON-CURRENT ASSETS"]

    def test_a_row_that_titles_a_band_is_not_also_a_field(self):
        cells = {"0,0": "Earnings", "1,0": "Description", "1,1": "Amount",
                 "4,0": "Total Earnings"}
        shape = compute_shape(_drawn(cells))
        assert "Earnings" not in [f["row_label"] for f in shape["field_slots"]]
