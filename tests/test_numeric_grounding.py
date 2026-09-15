"""Numeric grounding is token equality, not substring.

`verify_span` accepted a number if it was a SUBSTRING of its span, if its
digits were a substring of the span's digits (rule B), or if it equalled a
span number rounded to two decimals (rule C). Against a printed `$0.04116`,
all of `0.04`, `$0.04`, `0.041`, `$40.4` and `4042` grounded as `high`: a rounded
or truncated answer stored as verbatim, which no export fix can recover.

A number now grounds only if it is the same number as a WHOLE printed token,
differing only in notation: whitespace, currency symbol, thousands
separators, parentheses as minus. Same digits, same decimal point.

Rule B was not idle, though. On the gold corpus it never fired, but on the
Berkshire earnings release (round 2, feb2225.pdf) pdfplumber splits numbers
across words — `19,6` + `94`, `9` + `.` + `13`, `2,157,034,1` + `21` — and B was
the only thing grounding the model's correctly repaired `$ 19,694`. So the
split is rejoined, and rejoining is the risky part: `$ 848 $ 9,020` must never
become `8489`.

Every line below is read off the real PDF.
"""
import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()


@pytest.fixture(scope="module")
def berkshire(pdf_dir):
    """(text lines, word lines) of pages 1-2, as the pipeline reads them."""
    import pdfplumber
    from text_layer import read_page
    texts, words = [], []
    with pdfplumber.open(pdf_dir / "round2" / "feb2225.pdf") as pdf:
        for page in pdf.pages[:2]:
            text, lines, _r = read_page(page)
            texts += text.splitlines()
            words += lines
    return texts, words


def _line(texts, key):
    return next(l for l in texts if key in l)


def _numbers(line):
    from slot_extractor import printed_numbers
    return printed_numbers(line)


# ══════════════════════════════════════════════════════════════════════════
# token rejoining — on the real Berkshire lines
# ══════════════════════════════════════════════════════════════════════════

class TestASplitNumberIsRejoined:
    def test_a_comma_group_split_across_words(self, berkshire):
        line = _line(berkshire[0], "Net earnings attributable to Berkshire")
        assert "$ 19,6 94" in line, "premise: the text layer splits it"
        assert _numbers(line)[:2] == ["$19,694", "$37,574"]

    def test_a_long_number_split_in_its_last_group(self, berkshire):
        line = _line(berkshire[0], "Class B shares outstanding")
        assert "2,157,034,1 21" in line
        assert _numbers(line) == ["2,157,034,121", "2,164,177,636",
                                  "2,156,580,296", "2,173,319,709"]

    def test_a_decimal_point_split_into_its_own_word(self, berkshire):
        line = _line(berkshire[0], "Class B Share ")
        assert "$ 9 . 13" in line
        assert _numbers(line) == ["$9.13", "$17.36", "$41.27", "$44.27"]

    def test_the_next_column_starts_its_own_number(self, berkshire):
        line = _line(berkshire[0], "Investment gains/losses")
        assert "5,1 67 29,093" in line
        assert _numbers(line) == ["5,167", "29,093", "41,558", "58,873"]


class TestNothingJoinsAcrossAColumn:
    def test_adjacent_currency_columns_stay_apart(self, berkshire):
        """`$ 848 $ 9,020` must not yield 8489 or any cross-column join."""
        line = _line(berkshire[0], "Insurance-underwriting")
        assert "$ 848 $ 9,020" in line
        got = _numbers(line)
        assert got == ["$3,409", "$848", "$9,020", "$5,428"]
        assert not any("8489" in n.replace(",", "") for n in got)

    def test_a_complete_number_never_absorbs_the_next(self):
        """Only an INCOMPLETE piece continues: nothing in `18` says it was cut
        short, so `18 000` is two numbers, not 18,000."""
        assert _numbers("18 000") == ["18", "000"]
        assert _numbers("1,268.7 5") == ["1,268.7", "5"]
        assert _numbers("848 9,020") == ["848", "9,020"]

    def test_a_gap_wider_than_one_space_never_joins(self):
        """The flattened text puts exactly one space where the word boxes
        touch; anything wider is not intra-number spacing."""
        assert _numbers("19,6  94") == ["19,6", "94"]
        assert _numbers("9  .  13") == ["9", "13"]

    def test_every_join_on_the_real_page_is_across_touching_words(self, berkshire):
        """The premise the string rule rests on, checked on real geometry.
        The rule never sees a gap; it sees only whether a number is complete.
        So check both directions on every adjacent pair of numeric words: a
        pair it joins touches (under 1pt), and a pair that touches is joined.
        Measured here: joins -0.1 to 0.1pt; the next-closest numeric pair,
        prose `22,` `2025`, 3.0pt; table columns 13.7 to 50pt.

        ⚠ 1pt is a TEST threshold read off this document, not a rule in the
        code. It checks the premise here; it says nothing about other fonts."""
        import re
        from slot_extractor import printed_numbers
        number_word = re.compile(r"[$(]?\d[\d,.]*\)?")
        joined_pairs, checked = 0, 0
        for ln in berkshire[1]:
            ws = sorted(ln, key=lambda w: float(w["x0"]))
            for a, b in zip(ws, ws[1:]):
                if not (number_word.fullmatch(a["text"])
                        and number_word.fullmatch(b["text"])):
                    continue           # the lone `.` case is tested above
                gap = float(b["x0"]) - float(a["x1"])
                joined = len(printed_numbers(f"{a['text']} {b['text']}")) == 1
                assert joined == (gap < 1.0), (a["text"], b["text"], gap, joined)
                joined_pairs += joined
                checked += 1
        assert checked > 20 and joined_pairs >= 5, (checked, joined_pairs)


# ══════════════════════════════════════════════════════════════════════════
# grounding
# ══════════════════════════════════════════════════════════════════════════

RATE_LINE = ("For power outages and other Fixed Price Energy Charge "
             "982kWh @ $0.04116 $40.42")


class TestATruncatedOrRoundedNumberDoesNotGround:
    @pytest.mark.parametrize("value", ["0.04", "0.041", "$40.4", "4042", "$0.04"])
    def test_rejected(self, value):
        """THE EVIDENCE. At 51e604d every one of these grounds as high."""
        from slot_extractor import verify_span
        ok, why = verify_span(value, RATE_LINE, 1, [RATE_LINE])
        assert not ok, f"{value!r} grounded against {RATE_LINE!r}"

    @pytest.mark.parametrize("value", ["$0.04116", "0.04116", "$40.42", "40.42",
                                       "982"])
    def test_the_same_number_in_other_notation_still_grounds(self, value):
        from slot_extractor import verify_span
        assert verify_span(value, RATE_LINE, 1, [RATE_LINE])[0], value

    @pytest.mark.parametrize("value,printed", [
        ("-1,234.50", "(1,234.50)"), ("$ 7,750.00", "$7,750.00"),
        ("7750.00", "$7,750.00"), ("021000021", "Routing 021000021"),
    ])
    def test_notation_only_differences(self, value, printed):
        from slot_extractor import verify_span
        assert verify_span(value, printed, 1, [printed])[0], (value, printed)

    @pytest.mark.parametrize("value,printed", [
        ("7,750", "$7,750.00"),          # a decimal point the page printed
        ("1,234.50", "(1,234.50)"),      # a sign the page printed
        ("2024", "INV-2024-0031"),       # a fragment of an identifier
    ])
    def test_a_different_number_is_not_notation(self, value, printed):
        from slot_extractor import verify_span
        assert not verify_span(value, printed, 1, [printed])[0], (value, printed)


class TestTheBerkshireValuesStillGround:
    """The 11 values the model repaired or wrote without a symbol, each
    against its real line. Rule B was grounding the seven split ones."""
    CASES = [
        ("Net earnings attributable to Berkshire", "$ 19,694"),
        ("Investment gains/losses", "5,167"),
        ("Operating earnings ....", "14,527"),
        ("Class A Share ", "$ 13,695"),
        ("Class B Share ", "$ 9.13"),
        ("Class A shares outstanding", "1,438,022"),
        ("Class B shares outstanding", "2,157,034,121"),
        ("Insurance-underwriting", "3,409"),
        ("Insurance-underwriting", "848"),
        ("Insurance-underwriting", "9,020"),
        ("Insurance-underwriting", "5,428"),
    ]

    @pytest.mark.parametrize("key,value", CASES)
    def test_grounds(self, berkshire, key, value):
        from slot_extractor import verify_span
        line = _line(berkshire[0], key)
        assert verify_span(value, line, 1, [line])[0], (value, line)
