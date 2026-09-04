"""
Positional evidence: the geometry the pipeline reads a PDF with.

Two things are proved here, and one of them is the regression fixture for the
worst defect the corpus contains.

WRAPPED VALUES. `FORM-W2-2023.pdf` renders its figures inside narrow boxes, so
the PDF itself wraps them: `$1,268.7` on one line and `5` on the next. Both
halves are genuinely printed on the page, so both halves ground perfectly, and
before this module a live run of that document returned ELEVEN WRONG VALUES OUT
OF TWELVE — every one marked HIGH — while the one correct value was the only
one marked LOW. The confidence signal was exactly inverted. The fragments are
recoverable because they share their parent's right edge to the point and sit
on the next line down.

PLACEMENT. Grounding answers "is this value in the document". It cannot answer
"does this value belong in THIS column", because a flattened line has no
columns in it — which is why a Debit written into the Credit column passed
every check the pipeline had. Column bands read off the document's own heading
line answer it directly.

The safety tests matter as much as the capability ones. A repair that fuses
two numbers that were never one number INVENTS a figure, which is the worst
thing this codebase can do, so every guard against that has a test.
"""
import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from text_layer import (  # noqa: E402
    check_placement, column_bands, find_line, group_lines, read_page,
    repair_wrapped, text_from_lines,
)


def W(text, x0, x1, top):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 10}


# ══════════════════════════════════════════════════════════════════════════
# LINE GROUPING
# ══════════════════════════════════════════════════════════════════════════

class TestLinesAreClusteredNotBucketed:
    def test_words_a_hair_apart_are_one_line(self):
        """Bucketing on `top / tol` splits any line that straddles a bucket
        edge. Two words 0.7pt apart fell either side of one on FORM-W2-2023,
        which broke a printed line in two, put a fragment TWO lines below its
        parent instead of one, and lost four of the twelve repairs."""
        lines = group_lines([W("comp.", 10, 40, 127.4), W("00", 280, 298, 128.1)])
        assert len(lines) == 1
        assert [w["text"] for w in lines[0]] == ["comp.", "00"]

    def test_genuinely_separate_lines_stay_separate(self):
        lines = group_lines([W("a", 10, 20, 100.0), W("b", 10, 20, 118.0)])
        assert len(lines) == 2

    def test_a_line_is_ordered_left_to_right(self):
        lines = group_lines([W("z", 300, 320, 50), W("a", 10, 30, 50)])
        assert [w["text"] for w in lines[0]] == ["a", "z"]


# ══════════════════════════════════════════════════════════════════════════
# WRAPPED VALUES — the repair
# ══════════════════════════════════════════════════════════════════════════

class TestItReassemblesValuesThePdfWrapped:
    @pytest.mark.parametrize("parent,fragment,expected", [
        ("$14,210.", "00", "$14,210.00"),       # bare decimal point, 2 cents
        ("$1,268.7", "5", "$1,268.75"),         # one decimal digit, missing 1
        ("$7,440.0", "0", "$7,440.00"),
        ("$144,58", "3.00", "$144,583.00"),     # cut comma group + its cents
        ("$160,20", "0.00", "$160,200.00"),
        ("$5,182.6", "5", "$5,182.65"),         # the payslip NET PAY
    ])
    def test_a_fragment_flush_with_its_parent_is_fused(self, parent, fragment, expected):
        lines, repairs = repair_wrapped([
            W(parent, 260.0, 298.8, 115.1),
            W(fragment, 293.2, 298.8, 128.1),
        ])
        assert repairs == [(parent, fragment, expected)]
        assert text_from_lines(lines).split() == [expected]

    def test_the_fragment_does_not_survive_on_its_own_line(self):
        """Left behind, a stray '5' is a value the model can answer some other
        slot with — and it would ground, because it is printed."""
        lines, _ = repair_wrapped([
            W("$1,268.7", 260.0, 298.8, 115.1),
            W("Box 6", 10.0, 60.0, 128.1),
            W("5", 293.2, 298.8, 128.1),
        ])
        assert "5" not in text_from_lines(lines).split()
        assert "$1,268.75" in text_from_lines(lines)


class TestItNeverInventsANumber:
    def test_two_complete_figures_sharing_a_right_edge_are_not_fused(self):
        """A right-aligned money column stacks figures with identical right
        edges by construction. Fusing a Balance of 199,320.55 into the one
        below it would invent a number out of two correct ones."""
        _, repairs = repair_wrapped([
            W("$199,320.55", 500.0, 559.92, 100.0),
            W("$180,870.55", 500.0, 559.92, 118.0),
        ])
        assert repairs == []

    def test_a_bare_integer_is_never_treated_as_cut_short(self):
        """Nothing in '18' says it was truncated, so '18' over '000' stays two
        numbers. Deliberately conservative: a missed repair is a visible
        wrong value, a false repair is an invisible one."""
        _, repairs = repair_wrapped([
            W("18", 280.0, 298.8, 100.0),
            W("000", 280.0, 298.8, 113.0),
        ])
        assert repairs == []

    def test_a_fragment_of_the_wrong_length_is_refused(self):
        """'1,268.7' is missing exactly one digit. '55' is not its tail."""
        _, repairs = repair_wrapped([
            W("$1,268.7", 260.0, 298.8, 100.0),
            W("55", 288.0, 298.8, 113.0),
        ])
        assert repairs == []

    def test_a_fragment_in_a_different_column_is_refused(self):
        _, repairs = repair_wrapped([
            W("$1,268.7", 260.0, 298.8, 100.0),
            W("5", 100.0, 106.0, 113.0),
        ])
        assert repairs == []

    def test_a_fragment_two_lines_down_is_refused(self):
        _, repairs = repair_wrapped([
            W("$1,268.7", 260.0, 298.8, 100.0),
            W("something", 10.0, 60.0, 113.0),
            W("5", 293.2, 298.8, 126.0),
        ])
        assert repairs == []


# ══════════════════════════════════════════════════════════════════════════
# THE REGRESSION FIXTURE — FORM-W2-2023
# ══════════════════════════════════════════════════════════════════════════

#: Every figure the W-2 prints, and the truncation the flat text layer used to
#: hand the model in its place. Read off the page by eye, not off engine
#: output.
W2_FIGURES = [
    ("$87,500.00", "$87,500."),
    ("$14,210.00", "$14,210."),
    ("$5,425.00", "$5,425.0"),
    ("$1,268.75", "$1,268.7"),
    ("$4,812.00", "$4,812.0"),
    ("$144,583.00", "$144,58"),
    ("$38,880.00", "$38,880."),
    ("$160,200.00", "$160,20"),
    ("$9,932.40", "$9,932.4"),
    ("$2,096.46", "$2,096.4"),
    ("$10,560.00", "$10,560."),
    ("$55,274.00", "$55,274."),
    ("$7,440.00", "$7,440.0"),
    ("$3,427.00", "$3,427.0"),
    ("$2,616.00", "$2,616.0"),
]


@pytest.fixture(scope="module")
def w2_page(pdf_dir):
    import pdfplumber
    with pdfplumber.open(pdf_dir / "FORM-W2-2023.pdf") as pdf:
        yield read_page(pdf.pages[0])


class TestTheW2ComesBackWhole:
    def test_every_printed_figure_is_in_the_text_the_model_reads(self, w2_page):
        text, _, _ = w2_page
        missing = [full for full, _ in W2_FIGURES if full not in text]
        assert missing == [], f"still truncated in the text layer: {missing}"

    def test_no_truncated_figure_is_left_for_the_model_to_answer_with(self, w2_page):
        text, _, _ = w2_page
        import re
        alive = [cut for full, cut in W2_FIGURES
                 if re.search(re.escape(cut) + r"(?!\d)", text)]
        assert alive == [], f"truncated forms still readable: {alive}"

    def test_it_says_what_it_changed(self, w2_page):
        """A silent rewrite of a number is not something this pipeline may do."""
        _, _, repairs = w2_page
        assert len(repairs) == 20
        for parent, fragment, fused in repairs:
            assert fused == parent + fragment


class TestPagesThatNeedNothingAreUntouched:
    def test_text_is_returned_verbatim_when_there_is_no_repair(self, pdf_dir):
        """Rebuilding word lists into text is NOT byte-identical to
        extract_text — 30 of the corpus's 77 pages differ — and the text is
        part of the prompt. Rewriting a page that had nothing wrong with it
        would change what the model is asked and invalidate its cached
        answer for no reason."""
        import pdfplumber
        with pdfplumber.open(pdf_dir / "STMT-2024-01.pdf") as pdf:
            page = pdf.pages[0]
            raw = page.extract_text()
            text, _, repairs = read_page(page)
        assert repairs == []
        assert text == raw


# ══════════════════════════════════════════════════════════════════════════
# PLACEMENT — which column a value sits under
# ══════════════════════════════════════════════════════════════════════════

HEADERS = ["Date", "Type", "Description", "Debit", "Credit", "Balance"]
COLUMNS = [{"col": i, "header": h, "key": h} for i, h in enumerate(HEADERS)]


@pytest.fixture(scope="module")
def stmt_lines(pdf_dir):
    import pdfplumber
    with pdfplumber.open(pdf_dir / "STMT-2024-01.pdf") as pdf:
        _, lines, _ = read_page(pdf.pages[0])
    return lines


class TestColumnBandsComeFromTheDocument:
    def test_the_heading_line_gives_every_column_its_span(self, stmt_lines):
        bands = column_bands(stmt_lines, HEADERS)
        assert set(bands) == set(HEADERS)
        # right-aligned money columns, left to right and non-overlapping
        assert bands["Debit"][1] < bands["Credit"][1] < bands["Balance"][1]

    def test_headings_the_document_does_not_print_get_no_band(self, stmt_lines):
        bands = column_bands(stmt_lines, ["Debit", "Credit", "Federal Tax"])
        assert "Federal Tax" not in bands

    def test_a_single_matching_heading_is_not_a_heading_line(self, stmt_lines):
        """One word matching is a coincidence, not a table header."""
        assert column_bands(stmt_lines, ["Balance"]) == {}


class TestItCatchesAValueInTheWrongColumn:
    def _row(self, debit, credit):
        return {"Date": "01/03", "Type": "DEP", "Description": "Wire deposit",
                "Debit": debit, "Credit": credit, "Balance": "$199,320.55"}

    def test_a_correctly_placed_row_draws_no_verdict(self, stmt_lines):
        bands = column_bands(stmt_lines, HEADERS)
        line = find_line(stmt_lines, "01/03 DEP Wire deposit")
        bad = check_placement(self._row("", "$15,000.00"), COLUMNS, line, bands)
        assert bad == []

    def test_a_credit_written_into_the_debit_column_is_caught(self, stmt_lines):
        """The whole of D6 in one assertion. Both spellings of this row quote
        the same source line and ground identically; only the geometry can
        tell them apart."""
        bands = column_bands(stmt_lines, HEADERS)
        line = find_line(stmt_lines, "01/03 DEP Wire deposit")
        bad = check_placement(self._row("$15,000.00", ""), COLUMNS, line, bands)
        assert [k for k, _ in bad] == ["Debit"]
        assert "Credit" in bad[0][1]

    def test_no_verdict_without_a_line_to_check_against(self, stmt_lines):
        bands = column_bands(stmt_lines, HEADERS)
        assert check_placement(self._row("", "$15,000.00"), COLUMNS, None, bands) == []

    def test_no_verdict_without_column_bands(self, stmt_lines):
        line = find_line(stmt_lines, "01/03 DEP Wire deposit")
        assert check_placement(self._row("$15,000.00", ""), COLUMNS, line, {}) == []
