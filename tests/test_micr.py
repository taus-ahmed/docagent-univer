"""
MICR decomposition, and the identifier rule it exposed.

A cheque's routing and account numbers are printed only inside the MICR band,
and the model returns the band whole: asked for a routing number it answers
"A021000021A C7743882201C 001847D". That is not a naming judgement and no
prompt fixes it — E-13B has a fixed format with a sentinel delimiting each
field, so it is parsed.
"""
import pytest

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


#: The 18 synthetic cheques of tests/test_OCR/_index.json, copied here so the
#: suite does not depend on that corpus being present. Each prints its band in
#: the BUSINESS layout — auxiliary on-us serial LEFT of the transit field:
#:     C<serial>C  A<routing>A  <account>C
#: The first parse_micr took the first on-us pair anywhere in the line, so on
#: all 18 it reported the serial as the account (0/18 account, 0/18 serial).
#: chk_009 and chk_016 are deliberately checksum-invalid.
BUSINESS_CHEQUES = [
    ("chk_001", "001001", "433218197", "600133890838", True),
    ("chk_002", "001002", "423511613", "559407816184", True),
    ("chk_003", "001003", "316475251", "534192832764", True),
    ("chk_004", "001004", "056413955", "376724238849", True),
    ("chk_005", "001005", "122691669", "978480184514", True),
    ("chk_006", "001006", "148932522", "880957015430", True),
    ("chk_007", "001007", "782489635", "834657871331", True),
    ("chk_008", "001008", "105183479", "382997376311", True),
    ("chk_009", "001009", "651333871", "624731781080", False),
    ("chk_010", "001010", "606474687", "723430980500", True),
    ("chk_011", "001011", "913619397", "909169985435", True),
    ("chk_012", "001012", "911838426", "513542784980", True),
    ("chk_013", "001013", "118244936", "534874016400", True),
    ("chk_014", "001014", "112805986", "262045053315", True),
    ("chk_015", "001015", "226025636", "421607337543", True),
    ("chk_016", "001016", "850142944", "196556981693", False),
    ("chk_017", "001017", "615951489", "465648236629", True),
    ("chk_018", "001018", "773872141", "895134332003", True),
]


class TestTheOnUsOrderIsReadFromStructure:
    """The on-us field is bank-defined, so which on-us group is the account is
    decided relative to the TRANSIT field, never by position in the string."""

    @pytest.mark.parametrize("cid,serial,routing,account,valid",
                             BUSINESS_CHEQUES, ids=[c[0] for c in BUSINESS_CHEQUES])
    def test_a_business_cheque_band(self, cid, serial, routing, account, valid):
        band = f"C{serial}C  A{routing}A  {account}C"
        assert aba_is_valid(routing) is valid
        want = {"account_number": account, "serial_number": serial}
        if valid:
            want["routing_number"] = routing
        assert parse_micr(band) == want

    def test_the_real_glyphs_in_the_business_layout(self):
        assert parse_micr("⑈001002⑈ ⑆423511613⑆ 559407816184⑈") == {
            "routing_number": "423511613", "account_number": "559407816184",
            "serial_number": "001002"}

    def test_an_account_with_a_dash_symbol_then_a_trailing_serial(self):
        """Certegy's documented TOAD example `T123456780T 1234d6678o 0691`:
        the dash sits INSIDE the account, the serial trails it."""
        assert parse_micr("T123456780T 1234d6678o 0691") == {
            "routing_number": "123456780", "account_number": "12346678",
            "serial_number": "0691"}

    def test_two_on_us_groups_and_no_auxiliary_field_is_left_unanswered(self):
        """Certegy's `T123456780T 0691o 123d6678o` is serial-then-account, and
        structurally identical to account-then-something. The routing checksum
        cannot break the tie — it checks the transit field — so the account is
        withheld rather than guessed. The routing number still stands."""
        assert parse_micr("T123456780T 0691o 123d6678o") == {
            "routing_number": "123456780"}

    def test_prose_after_a_transit_shaped_match_yields_no_account(self):
        """`find_micr_line` accepts `ABA: 021000021 Account: …` from an
        invoice's payment instructions (`:` and the `A` of `Account` are both
        transit stand-ins). The account parse must not reach into that prose.
        """
        assert parse_micr(
            "ABA: 021000021 Account: 7743882201 WT-20240210-4421.") == {
            "routing_number": "021000021"}


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
