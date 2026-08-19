"""
Shape regression tests against REAL production templates.

Every accuracy number in this repo comes from templates the harness author
built. These two are the repo owner's, taken read-only from the production
database, and both were found broken by verification C:

  Bank-Statement-101 (id 29) extracted ZERO transactions, because its
  transaction header is the last row of the grid and the band detector
  required empty rows beneath a header.

  BS Luq (id 31) cannot extract liabilities, because its section headers sit
  at columns 0 and 2 with a gap, which the band detector does not recognise.

Both are now fixed. Bank-Statement-101 by the edge-header rule, BS Luq by
DECLARATION: the template says its four sections are tables instead of leaving
the detector to work it out from where the labels landed. The detector's
failure on the undeclared grid is still asserted below, so it stays visible
rather than becoming folklore.

NOTE: the production copy of BS Luq carries no declarations yet — nothing here
writes to the production database. Its owner gets the fix by opening it in the
template editor, selecting each section (heading row included) and clicking
"Table ↓", then saving. These tests prove that is enough.
"""
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from template_shape import compute_shape, is_usable  # noqa: E402

FIXTURES = bs.REPO_DIR / "tests" / "fixtures" / "prod_templates"


def _shape(slug):
    data = json.loads((FIXTURES / f"{slug}.json").read_text(encoding="utf-8"))
    return compute_shape(data["grid"]), data["_source"]


class TestBankStatement101:
    """id 29 — the header row is the LAST row of the grid."""

    def test_the_transaction_band_is_detected(self):
        shape, src = _shape("bank_statement_101")
        assert src["template_id"] == 29
        bands = shape["repeat_bands"]
        assert len(bands) == 1, (
            "Bank-Statement-101 must yield a transaction band. Without it the "
            "template extracts header fields and NO transactions, which is the "
            "bug verification C found.")
        assert [c["header"] for c in bands[0]["columns"]] == [
            "Txn DT", "Type", "Description", "Debit"]

    def test_the_band_has_room_and_the_writer_can_grow_it(self):
        shape, _ = _shape("bank_statement_101")
        b = shape["repeat_bands"][0]
        assert b["end_row"] - b["start_row"] + 1 >= 5

    def test_its_header_fields_are_not_lost_to_the_band(self):
        """A band at the grid edge must not swallow the KV rows above it."""
        shape, _ = _shape("bank_statement_101")
        labels = [f["row_label"] for f in shape["field_slots"]]
        assert len(labels) == 13, labels
        for expected in ["Bank Name", "Acct Holder", "Stmt No", "Opening Bal",
                         "Closing Bal", "Total Credits", "Total Debits"]:
            assert expected in labels, (expected, labels)

    def test_it_routes_and_needs_four_columns(self):
        shape, _ = _shape("bank_statement_101")
        assert shape["required_columns"] == 4
        assert is_usable(shape)


class TestBsLuq:
    """id 31 — section headers at columns 0 and 2, separated by a gap."""

    def test_the_assets_band_is_detected(self):
        shape, src = _shape("bs_luq")
        assert src["template_id"] == 31
        names = [b["name"] for b in shape["repeat_bands"]]
        assert "table" in names or names, names
        cols = [c["header"] for c in shape["repeat_bands"][0]["columns"]]
        assert cols == ["Current assets", "Amount",
                        "Non current assets", "Amount"]

    def test_its_totals_are_field_slots(self):
        shape, _ = _shape("bs_luq")
        labels = [f["row_label"] for f in shape["field_slots"]]
        assert "Current assets Total" in labels
        assert "Non Current assets Total" in labels

    def test_undeclared_the_liabilities_sections_are_still_not_detected(self):
        """The detector's limit, recorded rather than hidden.

        'Current liabilities' sits at column 0 and 'Non current liabilities' at
        column 2, with an empty cell between them. A band header must be
        ADJACENT static cells, so this row is not one, and the four line-item
        rows beneath are unreachable. The rule that would catch it — a gapped
        label row is a section header — cannot be told apart from an ordinary
        two-up key/value row, and broke four other production templates when
        tried. Detection is not going to fix this; declaration is.
        """
        shape, _ = _shape("bs_luq")
        names = [b["name"] for b in shape["repeat_bands"]]
        assert not any("liabilit" in n.casefold() for n in names), names

    # What the user draws in the editor: each of the four sections selected as
    # the table it is, heading row included. Rows 0-3 are the two asset
    # sections side by side; rows 6-9 the two liability sections.
    DECLARED = [
        {"type": "table", "r1": 0, "c1": 0, "r2": 3, "c2": 1, "orientation": "rows"},
        {"type": "table", "r1": 0, "c1": 2, "r2": 3, "c2": 3, "orientation": "rows"},
        {"type": "table", "r1": 6, "c1": 0, "r2": 9, "c2": 1, "orientation": "rows"},
        {"type": "table", "r1": 6, "c1": 2, "r2": 9, "c2": 3, "orientation": "rows"},
    ]

    def _declared(self):
        data = json.loads((FIXTURES / "bs_luq.json").read_text(encoding="utf-8"))
        grid = dict(data["grid"])
        grid["regions"] = self.DECLARED
        return compute_shape(grid)

    def test_declaring_the_sections_gives_all_four_bands(self):
        """The fix. The template says what its tables are; nothing has to be
        inferred from where the labels happen to sit."""
        shape = self._declared()
        names = [b["name"] for b in shape["repeat_bands"]]
        assert names == ["Current assets", "Non current assets",
                         "Current liabilities", "Non current liabilities"], names
        assert all(b["declared"] for b in shape["repeat_bands"])

    def test_each_liability_section_gets_its_own_line_item_rows(self):
        """Not just detected — reachable. Three data rows each, under the
        section's own heading, in its own two columns."""
        shape = self._declared()
        by_name = {b["name"]: b for b in shape["repeat_bands"]}
        for name, col in [("Current liabilities", 0),
                          ("Non current liabilities", 2)]:
            b = by_name[name]
            assert (b["header_row"], b["start_row"], b["end_row"]) == (6, 7, 9)
            assert [c["col"] for c in b["columns"]] == [col, col + 1]

    def test_the_two_asset_sections_stop_being_one_four_column_band(self):
        """Undeclared, both asset sections share one header row, so they are
        read as a single 4-column table — 'Non current assets' becomes a COLUMN
        of the current-assets table rather than a section of its own."""
        undeclared, _ = _shape("bs_luq")
        assert len(undeclared["repeat_bands"]) == 1
        assert len(undeclared["repeat_bands"][0]["columns"]) == 4

        shape = self._declared()
        assets = [b for b in shape["repeat_bands"] if "assets" in b["name"]]
        assert len(assets) == 2
        assert all(len(b["columns"]) == 2 for b in assets)

    def test_the_totals_rows_are_still_field_slots(self):
        """Declaring the sections must not swallow the totals that sit
        directly beneath them."""
        shape = self._declared()
        labels = [f["row_label"] for f in shape["field_slots"]]
        for expected in ["Current assets Total", "Non Current assets Total",
                         "Current liabilities Total",
                         "Non current liabilities Total"]:
            assert expected in labels, (expected, labels)


class TestNoProductionTemplateIsUnusable:
    def test_both_fixtures_yield_a_usable_shape(self):
        for slug in ("bank_statement_101", "bs_luq"):
            shape, src = _shape(slug)
            assert is_usable(shape), src
