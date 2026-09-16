"""Round 2 — the four defects that reached real documents past green fixtures.

Each of these was fixed and deployed BEFORE round 2 ran, and each was reported
again against the build carrying its own fix. None of them was a bad fix; every
one was a fix verified against a fixture that is easier than the product.

  I7   a value read off a region where two texts are printed over one another
  I9   a column verdict that could only ever fire on a table
  I13  auto-fit made unreachable by the editor's own default widths
  I14  the look dropped from the one part of a table template that is drawn

`tests/fixtures/editor_grids.py` says what the fixtures were missing.
"""
import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from tests.fixtures.editor_grids import (  # noqa: E402
    EDITOR_DEFAULT_COL_PX, as_editor_saves, bordered_table_grid,
    long_label_grid)
from text_layer import (  # noqa: E402
    overprinted_spans, overprinted_value, read_page, unprinted_headers)

ROUND2 = "round2"
H25B = "201403_cfpb_closing-disclosure_cover-H25B.pdf"


@pytest.fixture(scope="module")
def engie_page4(pdf_dir):
    """SampleBill.pdf page 4 — its account number is printed twice, over itself."""
    import pdfplumber
    with pdfplumber.open(pdf_dir / ROUND2 / "SampleBill.pdf") as pdf:
        page = pdf.pages[3]
        text, lines, _r = read_page(page)
        spans = overprinted_spans(page)
    return text, lines, spans


# ══════════════════════════════════════════════════════════════════════════
# I7 — two texts printed over one another
# ══════════════════════════════════════════════════════════════════════════

class TestTheTwoOverprintedTextsAreSEPARATED:
    """SUPERSEDED, and the supersession is the point (I10, DECISION-LOG §21).

    This class used to assert that SampleBill page 4's two account numbers are
    NOT recoverable — "characters are the only level at which the two texts are
    separable", "nothing is repaired", "which one was wanted is not recoverable".
    That was true of a SIZE-BLIND reading and is false now. The two numbers are
    set at 11.0pt and 10.2pt, and `read_page` no longer lets a word span a font
    size, so both come back whole:

        was   00000000112538645596      one word, nothing on the page prints it
        now   0000123456 0000158659     both numbers, in the words AND the text

    I7's headline defect is therefore no longer DETECTED. It is GONE. The tests
    below assert that, because a passing test for a detector that fires on
    nothing is worse than no test at all.

    ⚠ The detector is not gone, and `TestSameSizeOverprintIsStillCaught` keeps
    it honest: two texts overlapping at the SAME size are still unrecoverable
    and still flagged.
    """

    ARTIFACT = "00000000112538645596"

    def test_the_artifact_is_no_longer_in_the_text(self, engie_page4):
        """The prompt too, not only the geometry. Recovering a value and then
        still showing the model the interleaving would be the worst of the
        three states — see `_recovered_words_missing`."""
        text, _lines, _s = engie_page4
        assert self.ARTIFACT not in text

    def test_both_real_numbers_are_recovered(self, engie_page4):
        text, lines, _s = engie_page4
        words = [w["text"] for ln in lines for w in ln]
        assert self.ARTIFACT not in words
        assert "0000123456" in words and "0000158659" in words
        assert "0000123456" in text and "0000158659" in text

    def test_the_page_no_longer_reports_an_overprint(self, engie_page4):
        """Cross-size overlap is two separable texts, not an interleaving.
        Counting it as one made the detector condemn the values this fix had
        just rescued — 13 words on this document, 910 on HTR-043235."""
        _t, _l, spans = engie_page4
        assert spans == []

    def test_nothing_on_the_page_is_flagged_as_overprinted(self, engie_page4):
        _t, lines, _s = engie_page4
        assert [w["text"] for ln in lines for w in ln
                if w.get("overprinted")] == []

    def test_a_clean_value_on_the_same_page_is_still_clean(self, engie_page4):
        _t, lines, _s = engie_page4
        assert overprinted_value("0123456789AB", lines) is False

    def test_kerning_is_not_overprinting(self, pdf_dir):
        """H25B sets one apostrophe-s pair tight enough for the two characters
        to overlap. An ISOLATED overlap is a font doing its job; a RUN of them
        is two texts."""
        import pdfplumber
        with pdfplumber.open(pdf_dir / ROUND2 / H25B) as pdf:
            spans = [s for p in pdf.pages for s in overprinted_spans(p)]
        assert spans == []

    @pytest.mark.parametrize("name,recovered", [
        ("AUD-2024-001-CLEAN-OPINION", "AUD-2024-001"),
        ("MGMT-LTR-2024-001", "MGMT-LTR-2024-001"),
        ("REV-2024-003-INTERIM-REVIEW", "REV-2024-003"),
    ])
    def test_the_gold_corpus_letterheads_now_read_correctly(
            self, pdf_dir, name, recovered):
        """These five letterheads interleaved their address (8.0pt) with their
        reference number (7.5pt) from the day they were committed. The words
        were verbatim garbage — `NSou:i`, `tAe`, `U2D20-200,`, `2N4e-w00` — and
        every one of them graded HIGH. They are now the words the page prints.
        """
        import pdfplumber
        with pdfplumber.open(pdf_dir / f"{name}.pdf") as pdf:
            words, spans = [], []
            for p in pdf.pages:
                words += [w["text"] for ln in read_page(p)[1] for w in ln]
                spans += overprinted_spans(p)
        assert recovered in words
        assert {"NSou:i", "tAe", "U2D20-200,", "2N4e-w00"} & set(words) == set()
        assert spans == [], "cross-size overlap is not an overprint"


class TestSameSizeOverprintIsStillCaught:
    """What the detector is FOR, now that font size explains the rest.

    Two texts overlapping at the same size are not separable by size or by
    anything else, so they are still reported. `round2/HTR-043235.pdf` is the
    corpus's only genuine case: page 3 sets several texts over one another at
    one size, and 1,037 of its overlapping same-size character pairs sit within
    half a point of the same baseline.
    """

    def test_it_still_fires_where_it_must(self, pdf_dir):
        import pdfplumber
        with pdfplumber.open(pdf_dir / ROUND2 / "HTR-043235.pdf") as pdf:
            spans = [s for p in pdf.pages for s in overprinted_spans(p)]
        assert len(spans) > 50, (
            "the one document with genuine same-size overprinting reports "
            "none — the detector has been turned into dead code")

    def test_a_clean_document_reports_none(self, pdf_dir):
        import pdfplumber
        with pdfplumber.open(pdf_dir / "STMT-2024-01.pdf") as pdf:
            assert [s for p in pdf.pages for s in overprinted_spans(p)] == []


# ══════════════════════════════════════════════════════════════════════════
# I9 — a column heading the document never says
# ══════════════════════════════════════════════════════════════════════════

class TestATemplateColumnTheDocumentDoesNotName:
    @pytest.fixture(scope="class")
    def cd_lines(self, pdf_dir):
        import pdfplumber
        out = []
        with pdfplumber.open(pdf_dir / ROUND2 / H25B) as pdf:
            for p in pdf.pages:
                out += read_page(p)[1]
        return out

    def test_an_invented_comparison_column_is_reported(self, cd_lines):
        """Run 10's template compares a Loan Estimate against a Closing
        Disclosure. No loan estimate was uploaded, and the document says
        `Variance` nowhere — so nothing but position decided what filled it."""
        assert unprinted_headers(
            cd_lines, ["Loan Estimate", "Closing Disclosure", "Variance"]
        ) == ["Variance"]

    def test_the_documents_own_headings_are_not_reported(self, cd_lines):
        """`Paid by Others` is set stacked in a narrow column: the page prints
        `Paid by` on one line and `Others` at the far END of the next. A
        per-line match and a reading-order match both called it missing, and a
        warning that fires on a heading the document plainly does print is one
        the user learns to scroll past."""
        assert unprinted_headers(
            cd_lines, ["Borrower-Paid", "Seller-Paid", "Paid by Others"]) == []

    def test_a_heading_from_another_document_entirely(self, cd_lines):
        assert unprinted_headers(cd_lines, ["Widget Count"]) == ["Widget Count"]


# ══════════════════════════════════════════════════════════════════════════
# I13 — auto-fit, against what the editor actually saves
# ══════════════════════════════════════════════════════════════════════════

class TestAWidthTheUserDidNotSetIsNotAWidth:
    def _fit(self, grid):
        from openpyxl import Workbook
        from app.api.routes.extract import _fit_columns
        ws = Workbook().active
        for key, cell in grid["cells"].items():
            r, c = (int(x) for x in key.split(","))
            if cell.get("value"):
                ws.cell(row=r + 1, column=c + 1).value = cell["value"]
            # touching the cell is what puts it in the sheet's extent, and a
            # value column carries no text — which is the whole of D14
            ws.cell(row=r + 1, column=c + 1)
        _fit_columns(ws, grid["colWidths"])
        return ws

    def test_the_editors_default_is_not_a_choice(self):
        """THE DEFECT. `colWidths` is `Array(26).fill(120)` on every template
        the editor has ever saved, so `_fit_columns` read a stored width for
        all 26 columns and its fit branch was unreachable. Every fixture in the
        repo saves `colWidths: []`, which is why this passed."""
        grid = long_label_grid()
        label = grid["cells"]["0,0"]["value"]
        ws = self._fit(grid)
        assert ws.column_dimensions["A"].width > round(
            EDITOR_DEFAULT_COL_PX / 7), "the default must not win"
        assert ws.column_dimensions["A"].width >= min(60, len(label))

    def test_a_width_the_user_really_dragged_still_wins(self):
        grid = as_editor_saves(long_label_grid(), sized={0: 700})
        assert self._fit(grid).column_dimensions["A"].width == 100

    def test_a_varied_array_is_still_honoured(self):
        """The rule is narrow on purpose: it fires only on an array whose every
        entry is the editor's own default, which carries no per-column
        information and cannot be a choice."""
        varied = as_editor_saves(long_label_grid(), sized={1: 350})
        assert self._fit(varied).column_dimensions["B"].width == 50


# ══════════════════════════════════════════════════════════════════════════
# I14 — the look of a table template
# ══════════════════════════════════════════════════════════════════════════

def _write(grid, rows):
    import openpyxl
    from app.api.routes.extract import _write_excel

    class _Doc:
        def get_extracted_data(self):
            return {
                "template_type": "slot",
                "extracted_fields": {"B7": "Jane Roe"},
                "Earnings_rows": rows,
                "slot_map": {
                    "fields": [{"ref": "B7", "row_label": "Prepared By"}],
                    "tables": [{
                        "name": "Earnings", "start_row": 2, "end_row": 4,
                        "start_col": 0, "end_col": 2, "orientation": "rows",
                        "columns": [
                            {"header": "Segment", "key": "Segment", "col": 0},
                            {"header": "2024", "key": "2024", "col": 1},
                            {"header": "2023", "key": "2023", "col": 2}],
                    }],
                },
            }

    ws = openpyxl.Workbook().active
    _write_excel(ws, [_Doc()], grid, {}, openpyxl)
    return ws


def _bordered(ws, ref):
    b = ws[ref].border
    return bool(b and b.left and b.left.style)


ROWS3 = [{"Segment": s, "2024": "1", "2023": "2"}
         for s in ("Insurance", "Railroad", "Utilities")]
ROWS5 = ROWS3 + [{"Segment": s, "2024": "1", "2023": "2"}
                 for s in ("Energy", "Other")]


class TestATableTemplateKeepsItsBox:
    def test_the_band_body_is_bordered(self):
        """THE DEFECT. `_write_slot_excel` applied style in the loop that
        `continue`s past every band row, so the one region of a table template
        a user actually draws — the box around its body — was the one region
        that arrived unstyled. D13 was verified on a form, which has no band."""
        ws = _write(bordered_table_grid(), ROWS3)
        for ref in ("A3", "B3", "C3", "A4", "B4", "C4", "A5", "B5", "C5"):
            assert _bordered(ws, ref), ref

    def test_a_row_beyond_the_band_takes_the_first_body_rows_look(self):
        """A band grows to the document's row count, so the rows the user drew
        are not the rows that get written."""
        ws = _write(bordered_table_grid(), ROWS5)
        assert _bordered(ws, "A6") and _bordered(ws, "C7")

    def test_the_heading_row_keeps_its_shading_and_centring(self):
        ws = _write(bordered_table_grid(), ROWS3)
        assert ws["A2"].fill.fgColor.rgb.endswith("DDDDDD")
        assert ws["A2"].alignment.horizontal == "center"
        assert ws["A2"].font.bold is True

    def test_a_merge_above_the_band_survives(self):
        ws = _write(bordered_table_grid(), ROWS3)
        assert "A1:C1" in [str(r) for r in ws.merged_cells.ranges]

    def test_fields_below_the_band_keep_their_look_after_it_expands(self):
        ws = _write(bordered_table_grid(), ROWS5)
        assert _bordered(ws, "A9"), "the Prepared By row, pushed down by two"


# ══════════════════════════════════════════════════════════════════════════
# the gap itself
# ══════════════════════════════════════════════════════════════════════════

class TestTheFixtureGapStaysClosed:
    def test_a_fixture_exists_that_carries_the_editors_own_widths(self):
        """Three defects hid behind `colWidths: []`. If every fixture in the
        repo goes back to that, this fails."""
        grid = bordered_table_grid()
        assert len(grid["colWidths"]) == 26
        assert all(w == EDITOR_DEFAULT_COL_PX for w in grid["colWidths"])

    def test_and_one_that_is_a_table_rather_than_a_form(self):
        grid = bordered_table_grid()
        assert any(cell.get("style", {}).get("borderAll") and not cell.get("value")
                   for cell in grid["cells"].values()), \
            "a table template's band body is drawn and empty"
