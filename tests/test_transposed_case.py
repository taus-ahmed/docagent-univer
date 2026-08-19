"""
A transposed template, end to end, against real gold.

The band detector describes one shape: headings across a row, records running
downwards. A transposed table — headings down a column, one record per column —
has no empty rows beneath a heading row, so nothing is detected and the
headings are read as unrelated single fields. Nothing errors; the answer is
just wrong. Declaration is what fixes it (see test_declared_regions.py); this
proves the fix survives the whole pipeline and lands correctly in the file.

`payslip_transposed.json` is the SAME payslip as `payslip.json` with its two
line-item tables laid sideways. Gold labels are keyed by field name and table
name, never by cell address, so both templates are scored against exactly the
same answers — which is what makes the comparison meaningful rather than a
second set of labels graded against itself.
"""
import contextlib
import io

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

DOC = "PAYSLIP-EMP-0007-APR2024"
ROW_TEMPLATE = "payslip.json"
COL_TEMPLATE = "payslip_transposed.json"


def _run(template):
    """The real pipeline, from the replay cache, plus the exported sheet."""
    from tests.harness.llm_cache import LLMCache
    from tests.harness.runner import (build_export, build_template_data,
                                      load_labels, run_pipeline)
    bs.chdir_backend()
    label = load_labels({DOC})[0]
    cache = LLMCache(mode="replay")
    cache.install()
    cache.context = DOC
    td, grid, _ = build_template_data(label, "replay", template_override=template)
    with contextlib.redirect_stdout(io.StringIO()):
        results, _log = run_pipeline(label, td)
        ws, shape = build_export(results, grid, False)
    return label, results, ws, shape, grid


def _score(label, results, grid):
    from tests.harness.adapter import adapt
    from tests.harness.scoring import score_document
    return score_document(label, adapt(results, label, grid), doc_text="")


@pytest.fixture(scope="module")
def transposed():
    return _run(COL_TEMPLATE)


class TestItExtractsAsWellAsTheUprightTemplate:
    def test_the_same_document_scores_the_same_either_way(self):
        """Orientation is a layout choice. If turning the sheet sideways cost
        accuracy, the declaration would not be worth having."""
        upright = _score(*[_run(ROW_TEMPLATE)[i] for i in (0, 1, 4)])
        sideways = _score(*[_run(COL_TEMPLATE)[i] for i in (0, 1, 4)])
        assert sideways["accuracy"] == pytest.approx(upright["accuracy"], abs=0.02), (
            sideways["accuracy"], upright["accuracy"])

    def test_both_line_item_tables_come_back(self, transposed):
        _, results, _, _, _ = transposed
        ed = results[0].extracted_data
        assert len(ed.get("earnings_rows") or []) == 3
        assert len(ed.get("deductions_rows") or []) == 9

    def test_the_rows_hold_the_documents_real_values(self, transposed):
        _, results, _, _, _ = transposed
        rows = results[0].extracted_data["earnings_rows"]
        assert [r["Description"] for r in rows] == [
            "Base Salary", "Car Allowance", "Executive Bonus"]


class TestTheFileIsWrittenSideways:
    def test_each_line_item_is_a_column(self, transposed):
        _, _, ws, _, _ = transposed
        assert [ws.cell(row=11, column=c).value for c in range(2, 5)] == [
            "Base Salary", "Car Allowance", "Executive Bonus"]
        assert [ws.cell(row=12, column=c).value for c in range(2, 5)] == [
            12083.33, 500.0, 2000.0]

    def test_the_heading_column_is_not_overwritten(self, transposed):
        """The transposed table's first column is the template's own labels.
        A writer that treated those rows as the table's to fill would erase
        them — the row-oriented writer does exactly that, correctly, which is
        why orientation has to reach the writer."""
        _, _, ws, _, _ = transposed
        assert [ws.cell(row=r, column=1).value for r in (11, 12, 17, 18)] == [
            "Description", "Amount", "Description", "Amount"]

    def test_more_records_than_drawn_columns_widen_the_sheet(self, transposed):
        """The template draws room for six records; this payslip has nine
        deductions. They must run further right, not wrap onto new rows —
        wrapping would split one record across two places."""
        _, _, ws, _, _ = transposed
        labels = [ws.cell(row=17, column=c).value for c in range(2, 11)]
        assert all(labels), labels
        assert labels[-1] == "Life Insurance"
        assert ws.cell(row=18, column=10).value == -28.0

    def test_the_totals_beneath_each_table_still_land(self, transposed):
        _, _, ws, _, _ = transposed
        assert ws.cell(row=14, column=1).value == "Total Earnings"
        assert ws.cell(row=14, column=2).value == 14583.33
        assert ws.cell(row=20, column=2).value == -7070.3


class TestExportMatchesExtraction:
    def test_reading_the_file_back_gives_what_was_extracted(self, transposed):
        """The check that caught the 2026-08-18 export bug, applied to the
        transposed writer: score the FILE, not the in-memory result."""
        from tests.harness.adapter import adapt
        from tests.harness.scoring import score_document
        from tests.harness.sheet_reader import sheet_as_result
        label, results, ws, shape, grid = transposed
        extracted = score_document(label, adapt(results, label, grid), doc_text="")
        exported = score_document(
            label, adapt([sheet_as_result(ws, shape)], label, grid), doc_text="")
        assert exported["accuracy"] == pytest.approx(extracted["accuracy"], abs=0.001)

    def test_the_reader_recovers_both_tables_from_the_sheet(self, transposed):
        from tests.harness.sheet_reader import read_sheet
        _, _, ws, shape, _ = transposed
        flat = read_sheet(ws, shape)
        assert len(flat["tables"]["earnings"]) == 3
        assert len(flat["tables"]["deductions"]) == 9
        assert flat["tables"]["earnings"][0]["Description"] == "Base Salary"
