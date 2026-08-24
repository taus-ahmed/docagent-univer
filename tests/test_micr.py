"""
MICR decomposition, and the identifier rule it exposed.

A cheque's routing and account numbers are printed only inside the MICR band,
and the model returns the band whole: asked for a routing number it answers
"A021000021A C7743882201C 001847D". That is not a naming judgement and no
prompt fixes it — E-13B has a fixed format with a sentinel delimiting each
field, so it is parsed.
"""
from tests.harness import bootstrap as bs

bs.bootstrap()

from app.api.routes.extract import coerce_cell_value  # noqa: E402
from micr import (  # noqa: E402
    aba_is_valid, field_role, find_micr_line, parse_micr,
)

ASCII = "A021000021A C7743882201C 001847D"
UNICODE = "⑆021000021⑆ ⑈7743882201⑈ 001847⑉"


class TestParsingTheBand:
    def test_the_ascii_rendering_splits_into_three(self):
        assert parse_micr(ASCII) == {"routing_number": "021000021",
                                     "account_number": "7743882201",
                                     "serial_number": "001847"}

    def test_the_real_e13b_glyphs_parse_identically(self):
        """PDF text extraction may preserve the sentinels or substitute ASCII
        for them, and which substitution depends on the font vendor."""
        assert parse_micr(UNICODE) == parse_micr(ASCII)

    def test_a_routing_number_failing_its_checksum_is_not_reported(self):
        """Nine digits in the transit position are not a routing number unless
        they check out. Reporting an unverified one would be exactly the
        confident wrong answer this engine exists to avoid."""
        bad = parse_micr("A021000022A C7743882201C 001847D")
        assert "routing_number" not in bad
        assert bad.get("account_number") == "7743882201"

    def test_prose_containing_a_nine_digit_number_is_not_a_band(self):
        assert parse_micr("Account 021000021 for reference") == {}
        assert parse_micr("") == {}

    def test_the_aba_checksum(self):
        assert aba_is_valid("021000021")
        assert not aba_is_valid("123456789")
        assert not aba_is_valid("02100002")     # eight digits

    def test_the_band_is_found_among_the_pages(self):
        pages = ["Pay to the order of…", ASCII + "  Non-Negotiable Copy"]
        assert find_micr_line(pages).startswith("A021000021A")
        assert find_micr_line(["nothing here"]) == ""


class TestWhichSlotWantsWhat:
    def test_the_standard_synonyms_all_mean_routing(self):
        for label in ("Routing Number", "ABA Number", "Bank ABA",
                      "Transit Number"):
            assert field_role(label) == "routing", label

    def test_account_number_means_account(self):
        assert field_role("Account Number") == "account"
        assert field_role("Account No") == "account"

    def test_account_holder_is_a_name_not_a_number(self):
        """The holder is a person. Filling it with an account number would be
        the misfiling this whole design is built to prevent."""
        assert field_role("Account Holder") == ""

    def test_an_unrelated_label_wants_nothing(self):
        for label in ("Payee", "Memo", "Bank Name", ""):
            assert field_role(label) == ""


class TestIdentifiersAreNotQuantities:
    """Found by the export-vs-extraction check, which is the only reason it did
    not ship: extraction held "021000021" and the SHEET held 21000021."""

    def test_a_leading_zero_is_never_dropped(self):
        assert coerce_cell_value("021000021") == "021000021"
        assert coerce_cell_value("00123") == "00123"

    def test_a_long_bare_digit_run_stays_text(self):
        assert coerce_cell_value("7743882201") == "7743882201"

    def test_money_is_still_a_number(self):
        assert coerce_cell_value("$1,365,503") == 1365503.0
        assert coerce_cell_value("1,365,503") == 1365503.0
        assert coerce_cell_value("(500)") == -500.0
        assert coerce_cell_value("12.5") == 12.5

    def test_a_count_is_still_a_number(self):
        """A quantity column must not become text just because it is bare."""
        assert coerce_cell_value("40") == 40.0
        assert coerce_cell_value("8410") == 8410.0
        assert coerce_cell_value("2024") == 2024.0
