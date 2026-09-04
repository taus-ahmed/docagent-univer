"""
Placement, end to end, and the notation the export keeps.

`test_text_layer.py` proves the geometry works. This proves the pipeline uses
it: that a value written into the wrong column comes out of
`run_slot_extraction` marked LOW and flagged with the column it actually sits
under, and that the exported cell still reads like money.

Both halves matter to the same reader. An accountant checking a bank statement
is asking two questions of every figure — is it the right number, and is it on
the right side of the ledger — and until now the pipeline could only answer the
first.
"""
import json

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from slot_extractor import run_slot_extraction  # noqa: E402
from template_shape import compute_shape  # noqa: E402
from text_layer import read_page  # noqa: E402


@pytest.fixture(scope="module")
def stmt(pdf_dir, templates_dir):
    """The real bank statement, its real text layer, its real template."""
    import pdfplumber
    with pdfplumber.open(pdf_dir / "STMT-2024-01.pdf") as pdf:
        text, lines, _ = read_page(pdf.pages[0])
    grid = json.loads((templates_dir / "bank_statement.json").read_text())
    shape = compute_shape(grid, log=lambda _m: None)
    return text, lines, grid, shape


def _stub(payload):
    class _Resp:
        success = True
        parsed_json = payload
        raw_text = json.dumps(payload)

    class _LLM:
        def extract(self, **kw):
            return _Resp()

    return type("O", (), {"llm": _LLM()})()


def _run(stmt, rows):
    text, lines, grid, shape = stmt
    band = shape["repeat_bands"][0]
    payload = {"fields": {}, "tables": {band["name"]: rows}}
    return run_slot_extraction(
        _stub(payload), "STMT-2024-01.pdf", {"layout": grid, "shape": shape},
        None, page_images=[], doc_text=text, doc_text_pages=[text],
        file_type="digital_pdf", default_doc_type="bank_statement",
        start=0.0, page_lines=[lines])[0].extracted_data, band["name"]


def _source(text, prefix):
    return next(l for l in text.split("\n") if l.startswith(prefix))


def _row(source, debit, credit):
    return {"cells": {"Date": "01/03", "Type": "DEP",
                      "Description": "Wire deposit", "Debit": debit,
                      "Credit": credit, "Balance": "$199,320.55"},
            "source": source, "page": 1}


class TestAMisplacedValueIsNoLongerConfident:
    def test_the_right_column_passes_clean(self, stmt):
        text, *_ = stmt
        ed, band = _run(stmt, [_row(_source(text, "01/03"), "", "$15,000.00")])
        assert ed["validation"]["misplaced_count"] == 0
        assert ed[f"{band}_rows"][0]["_confidence"] == "high"

    def test_a_credit_written_as_a_debit_is_caught_and_demoted(self, stmt):
        """Both spellings quote the SAME source line and ground identically.
        Nothing but the geometry can separate them, which is exactly why this
        was invisible: a deposit reported as a withdrawal, marked high."""
        text, *_ = stmt
        ed, band = _run(stmt, [_row(_source(text, "01/03"), "$15,000.00", "")])
        assert ed["validation"]["misplaced_count"] == 1
        assert ed[f"{band}_rows"][0]["_confidence"] == "low"

    def test_it_names_the_column_the_value_really_sits_under(self, stmt):
        text, *_ = stmt
        ed, _ = _run(stmt, [_row(_source(text, "01/03"), "$15,000.00", "")])
        flag = ed["validation"]["flagged_fields"][0]
        assert flag["value"] == "$15,000.00"
        assert "Credit" in flag["reason"]

    def test_the_value_is_kept_not_dropped(self, stmt):
        """A misplaced value is still evidence. Silently deleting it would
        trade a visible wrong cell for an invisible missing one."""
        text, *_ = stmt
        ed, band = _run(stmt, [_row(_source(text, "01/03"), "$15,000.00", "")])
        assert ed[f"{band}_rows"][0]["Debit"] == "$15,000.00"

    def test_the_document_says_so_in_its_notes(self, stmt):
        text, *_ = stmt
        ed, _ = _run(stmt, [_row(_source(text, "01/03"), "$15,000.00", "")])
        assert any("different column" in n for n in ed["validation_notes"])


class TestPlacementIsOnlyClaimedWhenItIsKnown:
    def test_no_geometry_means_no_verdict(self, stmt):
        """Every caller that predates positional evidence passes no lines.
        Those must behave exactly as before rather than acquire opinions."""
        text, lines, grid, shape = stmt
        band = shape["repeat_bands"][0]
        payload = {"fields": {},
                   "tables": {band["name"]: [_row(_source(text, "01/03"),
                                                  "$15,000.00", "")]}}
        ed = run_slot_extraction(
            _stub(payload), "STMT-2024-01.pdf", {"layout": grid, "shape": shape},
            None, page_images=[], doc_text=text, doc_text_pages=[text],
            file_type="digital_pdf", default_doc_type="bank_statement",
            start=0.0)[0].extracted_data
        assert ed["validation"]["misplaced_count"] == 0
        assert ed[f"{band['name']}_rows"][0]["_confidence"] == "high"


# ══════════════════════════════════════════════════════════════════════════
# D8 — the export keeps the notation as well as the number
# ══════════════════════════════════════════════════════════════════════════

class TestTheExportedCellStillReadsLikeMoney:
    @pytest.mark.parametrize("printed,value,fmt", [
        ("$155.00", 155.0, '"$"#,##0.00'),
        ("$7,750.00", 7750.0, '"$"#,##0.00'),
        ("1,980,000", 1980000.0, "#,##0"),
        ("(1,234.50)", -1234.5, "#,##0.00_);(#,##0.00)"),
        ("30", 30.0, "#,##0"),
    ])
    def test_the_cell_holds_the_number_and_displays_the_notation(
            self, printed, value, fmt):
        """The cell must stay a NUMBER — it has to sum — and still show the
        currency symbol and the second decimal an accountant reads."""
        from app.api.routes.extract import cell_format, coerce_cell_value
        assert coerce_cell_value(printed) == value
        assert cell_format(printed) == fmt

    @pytest.mark.parametrize("identifier", ["021000021", "47-3821654"])
    def test_an_identifier_gets_no_number_format(self, identifier):
        """A routing number is not a quantity and has no notation to keep."""
        from app.api.routes.extract import cell_format, coerce_cell_value
        assert coerce_cell_value(identifier) == identifier
        assert cell_format(identifier) is None

    def test_the_writer_applies_it(self, stmt):
        import openpyxl
        from openpyxl import Workbook
        from app.api.routes.extract import _write_slot_excel
        text, *_ = stmt
        ed, _ = _run(stmt, [_row(_source(text, "01/03"), "", "$15,000.00")])
        _, _, grid, _ = stmt

        class _Doc:
            def get_extracted_data(self):
                return ed

        ws = Workbook().active
        _write_slot_excel(ws, [_Doc()], grid, grid["cells"], openpyxl)
        money = [c for row in ws.iter_rows() for c in row
                 if isinstance(c.value, float) and c.value == 15000.0]
        assert money, "the credit did not reach the sheet"
        assert money[0].number_format == '"$"#,##0.00'


# ══════════════════════════════════════════════════════════════════════════
# THE W-2, END TO END
# ══════════════════════════════════════════════════════════════════════════

#: What the W-2 actually prints, per employee: Box 1, Box 2, Box 5, Box 6.
W2_TRUTH = {
    "Marcus A. Thompson": ("87500.00", "14210.00", "87500.00", "1268.75"),
    "Janet L. Wu": ("144583.00", "38880.00", "144583.00", "2096.46"),
    "Priya S. Nair": ("55274.00", "7440.00", "55274.00", "801.47"),
}
W2_COLUMNS = ("Box 1 Wages", "Box 2 Fed Tax",
              "Box 5 Medicare Wages", "Box 6 Medicare Tax")


def _plain(v):
    return str(v or "").replace("$", "").replace(",", "").rstrip(".")


@pytest.mark.live
class TestTheW2ExtractsWhole:
    """The bar this work had to clear, against the live model.

    Before positional evidence: 11 of 12 figures WRONG, every one marked
    HIGH, and the single correct figure the only one marked LOW. Deselected
    by default (it costs a call); the deterministic half of the same fixture
    is in test_text_layer.py and runs every time.
    """

    def test_every_figure_comes_back_as_printed(self, pdf_dir, repo_dir):
        import time
        from core.preprocessor import preprocess_file
        from connectors.llm_router import LLMRouter

        _bs.chdir_backend()
        doc = preprocess_file(str(pdf_dir / "FORM-W2-2023.pdf"))
        grid = json.loads(
            (repo_dir / "tests/fixtures/w2_table.json").read_text())
        shape = compute_shape(grid, log=lambda _m: None)
        orch = type("O", (), {"llm": LLMRouter()})()

        ed = run_slot_extraction(
            orch, "FORM-W2-2023.pdf", {"layout": grid, "shape": shape}, None,
            page_images=[], doc_text=doc.extracted_text,
            doc_text_pages=doc.page_texts, file_type="digital_pdf",
            default_doc_type="form_w2", start=time.time(),
            page_lines=doc.page_lines)[0].extracted_data

        rows = {r["Employee"].strip(): r for r in ed["W2_rows"]}
        assert set(rows) == set(W2_TRUTH), sorted(rows)
        wrong = [(name, col, rows[name].get(col), want)
                 for name, truth in W2_TRUTH.items()
                 for col, want in zip(W2_COLUMNS, truth)
                 if _plain(rows[name].get(col)) != want]
        assert wrong == [], wrong
