"""
Canonical field vocabulary (Phase 9).

Inference used to invent field names, and invented different ones each run.
These tests pin the three things that make a closed vocabulary safe: it is
STANDARD terminology rather than whatever gold happens to say, it never limits
what gets reported, and the document's own printed label wins over it.
"""
from tests.harness import bootstrap as bs

bs.bootstrap()

from vocabulary import (  # noqa: E402
    GOLD_DIVERGENCE, canonical_fields, split_other, vocabulary_block,
)


class TestTheVocabularyIsStandardTerminology:
    def test_a_cheque_is_signed_by_a_drawer_not_a_payer(self):
        """The party who writes and signs a cheque is the DRAWER. Gold calls it
        'Payer Name'; the vocabulary does not follow gold."""
        names = [f["name"] for f in canonical_fields("cheque")]
        assert "Drawer Name" in names
        assert "Payer Name" not in names

    def test_a_cheques_two_amounts_are_named_apart(self):
        """A cheque states its amount in figures AND in words, and they can
        disagree — which is why both are printed. A field called just 'Amount'
        does not say which was read."""
        names = [f["name"] for f in canonical_fields("cheque")]
        assert "Amount in Figures" in names and "Amount in Words" in names
        assert "Amount" not in names

    def test_the_divergences_from_gold_are_recorded_not_hidden(self):
        pairs = {(g, s) for g, s, _why in GOLD_DIVERGENCE["cheque"]}
        assert ("Payer Name", "Drawer Name") in pairs
        for _gold, _std, why in GOLD_DIVERGENCE["cheque"]:
            assert len(why) > 40, "a divergence must say WHY"

    def test_money_and_dates_are_typed_from_the_registry(self):
        kinds = {f["name"]: f["kind"] for f in canonical_fields("sales_invoice")}
        assert kinds.get("Total Amount") == "money"
        assert kinds.get("Invoice Date") == "date"
        assert kinds.get("Vendor Name") == "text"

    def test_a_payslip_names_the_employer_as_well_as_the_employee(self):
        """A closed list with a hole in it does not mislabel the missing value,
        it LOSES it: told to prefer the listed names, the model dropped the
        employer entirely rather than reaching for the escape hatch."""
        names = [f["name"] for f in canonical_fields("payslip")]
        assert "Employer Name" in names and "Employee Name" in names


class TestItNeverLimitsWhatIsReported:
    def test_the_block_says_the_list_does_not_limit_coverage(self):
        block = vocabulary_block("sales_invoice")
        assert "NEVER LIMITS WHAT YOU REPORT" in block
        assert "other: " in block

    def test_the_printed_label_wins_over_the_list(self):
        """An invoice headed 'Bill To:' has a Bill To field. The page decides,
        which is both stable and the name the reader already sees — the list is
        for values the document does NOT label."""
        block = vocabulary_block("sales_invoice")
        assert "PRINTS a label" in block
        assert "Bill To" in block

    def test_an_unknown_document_type_gets_no_block(self):
        """No vocabulary means name things freely, exactly as before."""
        assert vocabulary_block("nonsense") == ""
        assert canonical_fields("nonsense") == []
        assert vocabulary_block("") == ""


class TestTheEscapeHatch:
    def test_the_prefix_is_stripped_and_flagged(self):
        assert split_other("other: Bank Address") == ("Bank Address", True)
        assert split_other("OTHER:  Printed Stamp") == ("Printed Stamp", True)

    def test_an_ordinary_label_is_untouched(self):
        assert split_other("Invoice Number") == ("Invoice Number", False)

    def test_a_label_merely_containing_other_is_not_an_escape(self):
        assert split_other("Other Current Assets") == ("Other Current Assets", False)


class TestSectionTotalsAreSplitInCode:
    """Whether the last line under a heading is that section's total has an
    arithmetic answer, so it is computed rather than asked for — the model got
    it wrong on every table, every time, however the rule was worded."""

    def _split(self, labels, heading):
        from shape_inference import _split_total
        return _split_total(labels, heading)

    def test_a_total_ends_its_section(self):
        rows, totals = self._split(
            ["Cash", "Inventory", "Total Current Assets"], "CURRENT ASSETS")
        assert rows == ["Cash", "Inventory"]
        assert totals == ["Total Current Assets"]

    def test_statement_aggregates_after_the_total_go_with_it(self):
        """'GROSS PROFIT' is a total by position, not by wording, and it sits
        after COGS' own total."""
        rows, totals = self._split(
            ["Opening Inventory", "Purchases", "Total COGS", "GROSS PROFIT"],
            "COST OF GOODS SOLD")
        assert rows == ["Opening Inventory", "Purchases"]
        assert totals == ["Total COGS", "GROSS PROFIT"]

    def test_a_data_row_that_reads_like_an_aggregate_survives(self):
        """A balance sheet's equity section lists 'Net Income YTD Q1' as a real
        row, BEFORE 'Total Equity'. Stripping trailing aggregate-looking labels
        would have deleted it."""
        rows, totals = self._split(
            ["Common Stock", "Retained Earnings", "Net Income YTD Q1",
             "Total Equity", "TOTAL LIABILITIES & EQUITY"],
            "SHAREHOLDERS' EQUITY")
        assert "Net Income YTD Q1" in rows
        assert totals == ["Total Equity", "TOTAL LIABILITIES & EQUITY"]

    def test_net_x_is_a_total_when_it_names_its_own_section(self):
        rows, totals = self._split(
            ["Gross Sales", "Less: Returns", "Net Revenue"], "REVENUE")
        assert rows == ["Gross Sales", "Less: Returns"]
        assert totals == ["Net Revenue"]

    def test_a_section_with_no_total_keeps_every_line(self):
        rows, totals = self._split(["Rent", "Utilities", "Marketing"],
                                   "OPERATING EXPENSES")
        assert rows == ["Rent", "Utilities", "Marketing"] and totals == []
