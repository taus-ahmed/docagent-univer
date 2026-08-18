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

The first is fixed and locked in below. The second is NOT fixed — the test
records the current behaviour and says so, so that whatever is decided about
it is a deliberate change rather than a silent drift.
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

    @pytest.mark.xfail(strict=True, reason=(
        "KNOWN, UNFIXED. The liabilities sections are headed 'Current "
        "liabilities' at column 0 and 'Non current liabilities' at column 2, "
        "with a gap between them. The band detector only recognises ADJACENT "
        "static cells as a header, so those two sections yield single field "
        "slots and their line-item rows are unreachable. A rule that treats a "
        "gapped label row as a section header was written and reverted: it "
        "cannot be distinguished from an ordinary two-up key/value row, and "
        "it broke four other production templates when tried. Awaiting a "
        "decision — see the Phase 4 report."))
    def test_the_liabilities_sections_are_bands(self):
        shape, _ = _shape("bs_luq")
        names = [b["name"] for b in shape["repeat_bands"]]
        assert any("liabilit" in n.casefold() for n in names), names


class TestNoProductionTemplateIsUnusable:
    def test_both_fixtures_yield_a_usable_shape(self):
        for slug in ("bank_statement_101", "bs_luq"):
            shape, src = _shape(slug)
            assert is_usable(shape), src
