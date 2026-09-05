"""
D9 — one join rule for multi-line values.
D14 — every written column gets a width.

Both were reported as NON-DETERMINISTIC: three different joins for one field
across runs, and auto-fit applying on some runs and not others. Neither was
random. The join was whatever the model returned, and the widths were applied
across an extent computed from cells carrying TEXT — so which columns got one
depended on where the template happened to have headings.

Both now have a stated rule and a geometry answer.
"""
import json

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from text_layer import canonical_value, read_page  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# D9 — the join
# ══════════════════════════════════════════════════════════════════════════

#: The four joins actually observed for INV-2024-0031's Notes field, across
#: cached runs of the SAME document. Three of them are wrong and one of the
#: wrong ones merges two side-by-side columns.
NOTES = "Payment received via wire transfer Feb 10, 2024. Ref: WT-20240210-4421."


@pytest.fixture(scope="module")
def invoice_lines(pdf_dir):
    import pdfplumber
    with pdfplumber.open(pdf_dir / "INV-2024-0031.pdf") as pdf:
        _text, lines, _r = read_page(pdf.pages[0])
    return lines


class TestOneJoinRule:
    def test_a_newline_join_becomes_a_space_join(self, invoice_lines):
        got, gutter = canonical_value(
            "Payment received via wire transfer Feb 10, 2024. Ref:\n"
            "WT-20240210-4421.", invoice_lines)
        assert got == NOTES
        assert gutter is False

    def test_words_fused_together_are_separated(self, invoice_lines):
        got, _g = canonical_value(
            "Paymentreceived via wire transfer Feb 10, 2024. Ref: "
            "WT-20240210-4421.", invoice_lines)
        assert got == NOTES

    def test_an_already_correct_join_is_unchanged(self, invoice_lines):
        """Idempotent, or it would churn every correct value it touched."""
        got, _g = canonical_value(NOTES, invoice_lines)
        assert got == NOTES

    def test_the_value_continues_within_its_own_column(self, invoice_lines):
        """Reading order interleaves side-by-side columns: after "Ref:" the
        next word in the flat text is the LEFT column's "ABA:", not this
        value's own continuation. The join steps over anything outside its
        block."""
        got, _g = canonical_value(
            "Payment received via wire transfer Feb 10, 2024. Ref:\n"
            "WT-20240210-4421.", invoice_lines)
        assert "ABA" not in got and "021000021" not in got


class TestItNeitherAddsNorDrops:
    def test_a_truncated_value_is_not_extended(self, invoice_lines):
        """THE DESIGN ANSWER, stated: a field does not absorb the next line
        just because one is there. Absorbing is how one field swallows
        another's value, and a short value is a visible fault where a
        swallowed one is not."""
        first_line = "Payment received via wire transfer Feb 10, 2024."
        got, _g = canonical_value(first_line, invoice_lines)
        assert got == first_line

    def test_a_value_that_matches_no_words_is_left_alone(self, invoice_lines):
        """Anything the model derived or reformatted — a MICR field, a
        renotated number — has no run of words to re-derive from."""
        assert canonical_value("A VALUE THAT IS NOT PRINTED HERE",
                               invoice_lines) is None

    def test_a_short_value_is_never_touched(self, invoice_lines):
        assert canonical_value("40", invoice_lines) is None

    def test_an_ordinary_single_line_value_is_unchanged(self, invoice_lines):
        got, _g = canonical_value("500 Commerce Drive, Chicago, IL 60601",
                                  invoice_lines)
        assert got == "500 Commerce Drive, Chicago, IL 60601"


class TestTwoColumnsMergedIntoOneValueIsReported:
    def test_crossing_a_gutter_is_detected(self, invoice_lines):
        """INV-2024-0031 lays Payment Instructions and Notes side by side.
        Ordinary word gaps on those lines are 2.3-2.6pt; the gutter is 122pt.
        A value spanning it has merged two blocks."""
        _got, gutter = canonical_value(
            "Wire: First National Bank of New York Payment received via wire "
            "transfer Feb 10, 2024. Ref:\nABA: 021000021 Account: 7743882201 "
            "WT-20240210-4421.", invoice_lines)
        assert gutter is True

    def test_the_merged_value_is_reported_not_trimmed(self):
        """Which half was wanted is not knowable here, so it is kept, marked
        low and flagged — the same treatment as any other value the engine
        cannot stand behind."""
        from slot_extractor import run_slot_extraction
        from template_shape import compute_shape
        import pdfplumber

        with pdfplumber.open(_bs.PDF_DIR / "INV-2024-0031.pdf") as pdf:
            text, lines, _r = read_page(pdf.pages[0])
        grid = {"cells": {"0,0": {"value": "Notes"}, "0,1": {"value": ""}},
                "colWidths": [], "merges": {}, "repeatRows": [], "regions": []}
        shape = compute_shape(grid, log=lambda _m: None)
        merged = ("Wire: First National Bank of New York Payment received via "
                  "wire transfer Feb 10, 2024. Ref: ABA: 021000021 Account: "
                  "7743882201 WT-20240210-4421.")
        payload = {"fields": {"F1": {"value": merged, "source": merged,
                                     "page": 1}}, "tables": {}}

        class _Resp:
            success = True
            parsed_json = payload
            raw_text = json.dumps(payload)

        class _LLM:
            def extract(self, **kw):
                return _Resp()

        orch = type("O", (), {"llm": _LLM()})()
        ed = run_slot_extraction(
            orch, "INV.pdf", {"layout": grid, "shape": shape}, None,
            page_images=[], doc_text=text, doc_text_pages=[text],
            file_type="digital_pdf", default_doc_type="sales_invoice",
            start=0.0, page_lines=[lines])[0].extracted_data

        assert ed["validation"]["merged_column_count"] == 1
        assert ed["validation"]["confidence_map"]["B1"] == "low"
        assert ed["needs_review"] is True
        assert any("column gutter" in f["reason"]
                   for f in ed["validation"]["flagged_fields"])
        assert ed["extracted_fields"]["B1"], "the value must be kept, not dropped"


# ══════════════════════════════════════════════════════════════════════════
# D14 — the widths
# ══════════════════════════════════════════════════════════════════════════

class TestEveryWrittenColumnGetsAWidth:
    def _sheet(self, col_widths):
        import openpyxl
        from openpyxl import Workbook
        from app.api.routes.extract import _fit_columns
        ws = Workbook().active
        ws["A1"] = "Item / Description"
        ws["B1"] = "Qty"
        ws["C1"] = "A rather long extracted value that would be truncated"
        ws["D1"] = "Total"
        _fit_columns(ws, col_widths)
        return ws

    def test_no_written_column_is_left_at_the_excel_default(self):
        """The defect: widths were applied across the TEXT-carrying extent, so
        columns the writer went on to fill got none and fell back to 8.43 —
        truncating extracted values and the user's own labels."""
        ws = self._sheet([])
        for col in "ABCD":
            assert ws.column_dimensions[col].width is not None, col
            assert ws.column_dimensions[col].width >= 8

    def test_a_column_with_no_stored_width_is_fitted_to_its_content(self):
        ws = self._sheet([])
        assert ws.column_dimensions["C"].width > ws.column_dimensions["B"].width

    def test_the_users_own_width_wins_where_there_is_one(self):
        """It is the width they dragged."""
        ws = self._sheet([700, 0, 0, 0])
        assert ws.column_dimensions["A"].width == 100

    def test_a_zero_or_missing_stored_width_falls_back_to_fitting(self):
        ws = self._sheet([0, None])
        assert ws.column_dimensions["A"].width >= len("Item / Description")

    def test_one_long_note_cannot_push_the_sheet_off_screen(self):
        import openpyxl
        from openpyxl import Workbook
        from app.api.routes.extract import _fit_columns
        ws = Workbook().active
        ws["A1"] = "x" * 500
        _fit_columns(ws, [])
        assert ws.column_dimensions["A"].width == 60

    def test_it_is_deterministic(self):
        """The reported symptom was 'applies on some runs and not others'."""
        widths = [tuple(self._sheet([]).column_dimensions[c].width
                        for c in "ABCD") for _ in range(3)]
        assert len(set(widths)) == 1, widths
