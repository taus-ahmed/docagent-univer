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

class TestOverprintIsSeenAtTheOnlyLevelItIsVisible:
    def test_the_artifact_is_in_the_flattened_text(self, engie_page4):
        """The premise. Nothing downstream could have caught this, because by
        the time anything looked, the string genuinely was on the page."""
        text, _lines, _s = engie_page4
        assert "00000000112538645596" in text

    def test_and_in_the_word_boxes_too(self, engie_page4):
        """The report assumed two vertically stacked numbers, which word boxes
        would separate. They do not: pdfplumber returns the interleaving as ONE
        word, so positional evidence at the WORD level is contaminated as well.
        Characters are the only level at which the two texts are separable."""
        _t, lines, _s = engie_page4
        words = [w["text"] for ln in lines for w in ln]
        assert "00000000112538645596" in words
        assert "0000123456" not in words and "0000158659" not in words

    def test_the_character_geometry_says_so(self, engie_page4):
        _t, _l, spans = engie_page4
        assert spans, "the overprinted region must be found"

    def test_the_value_is_flagged(self, engie_page4):
        _t, lines, _s = engie_page4
        assert overprinted_value("00000000112538645596", lines) is True

    def test_a_clean_value_on_the_same_page_is_not(self, engie_page4):
        """The check must not condemn the page it found a defect on."""
        _t, lines, _s = engie_page4
        assert overprinted_value("0123456789AB", lines) is False

    def test_nothing_is_repaired(self, engie_page4):
        """Both texts are printed, in full, in the same place. Which one was
        wanted is not recoverable, so the value is reported, never guessed."""
        _t, lines, _s = engie_page4
        words = [w["text"] for ln in lines for w in ln if w.get("overprinted")]
        assert words == ["00000000112538645596"]

    def test_kerning_is_not_overprinting(self, pdf_dir):
        """H25B sets one apostrophe-s pair tight enough for the two characters
        to overlap. An ISOLATED overlap is a font doing its job; a RUN of them
        is two texts."""
        import pdfplumber
        with pdfplumber.open(pdf_dir / ROUND2 / H25B) as pdf:
            spans = [s for p in pdf.pages for s in overprinted_spans(p)]
        assert spans == []

    @pytest.mark.parametrize("name", [
        "AUD-2024-001-CLEAN-OPINION", "MGMT-LTR-2024-001",
        "REV-2024-003-INTERIM-REVIEW",
    ])
    def test_the_gold_corpus_has_carried_this_all_along(self, pdf_dir, name):
        """Not a new defect, and not one round 2 introduced. These letterheads
        have been interleaving their address with their reference number since
        the day they were committed — unnoticed only because no slot ever asked
        for that line."""
        import pdfplumber
        with pdfplumber.open(pdf_dir / f"{name}.pdf") as pdf:
            spans = [s for p in pdf.pages for s in overprinted_spans(p)]
        assert spans, f"{name} prints two texts over one another"


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
