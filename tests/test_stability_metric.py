"""
Stability is measured on what the user actually receives.

A run-to-run difference only matters if the exported spreadsheet differs.
Comparing raw model strings reported 9 BS-2024-Q1 totals as unstable when every
run extracted the identical number and the workbook was byte-identical — that
measures the model's formatting, not its extraction, and it would send work in
the wrong direction.
"""
from tests.harness import bootstrap as bs

bs.bootstrap()

from app.api.routes.extract import coerce_cell_value  # noqa: E402
from tests.harness.runner import _stable_value  # noqa: E402


class TestCoerceCellValue:
    """The writer's own rule: money and numbers become numbers, because the
    currency symbol, the separators and the accounting parentheses are
    notation, not content."""

    def test_currency_and_separators_are_notation(self):
        assert coerce_cell_value("$1,365,503") == 1365503.0
        assert coerce_cell_value("1,365,503") == 1365503.0
        assert coerce_cell_value("£1 234") == "£1 234"     # space is not a separator

    def test_accounting_parentheses_are_negative(self):
        assert coerce_cell_value("($3,240.00)") == -3240.0

    def test_text_stays_text(self):
        assert coerce_cell_value("Janet Wu") == "Janet Wu"
        assert coerce_cell_value("1.5% monthly interest") == "1.5% monthly interest"

    def test_a_percentage_is_text_not_a_number(self):
        """It must not become 1.5 — the unit is part of the value."""
        assert coerce_cell_value("1.5%") == "1.5%"

    def test_empty_writes_nothing(self):
        assert coerce_cell_value("") is None
        assert coerce_cell_value(None) is None
        assert coerce_cell_value("   ") is None


class TestStabilityMeasuresTheCell:
    def test_two_spellings_of_one_number_are_stable(self):
        assert _stable_value("$1,365,503") == _stable_value("1,365,503")

    def test_two_spellings_of_one_negative_are_stable(self):
        assert _stable_value("($500)") == _stable_value("-500")

    def test_a_genuine_text_difference_is_still_unstable(self):
        """The rule must not swallow a real disagreement: neither of these
        parses as a number, so they stay different."""
        assert _stable_value("1.5%") != _stable_value("1.5% monthly interest")

    def test_two_different_numbers_are_still_unstable(self):
        assert _stable_value("$8,800") != _stable_value("$1,129,003")

    def test_none_stays_none(self):
        """A field present in one run and absent in another is the instability
        that matters most — it must not be normalised away."""
        assert _stable_value(None) is None
        assert _stable_value("Janet Wu") is not None
