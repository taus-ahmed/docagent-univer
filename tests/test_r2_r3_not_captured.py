"""Run R, R2 + R3 — what the document prints and the export does not hold.

R2 (job 95, carson_bank_6pg): 56 of 166 printed amounts were not in the
export. Three causes:
  * the checks table prints THREE checks per line; a row on a line another
    row had already claimed was dropped as a "duplicate", so 5 of 8 checks
    (and 13 daily-balance rows) went - fixed: a row whose every value sits
    on words of that line no earlier row used is a side-by-side record;
  * the daily balance summary is left out by design (Q2) and said only in a
    validation note - now in `not_captured`, shown in the export;
  * page 4 (a credit-line summary) printed 27 amounts, none in any cell, with
    no reason at all - now a completeness reason naming them.
R3 (job 115): the 1099-K a 1099-NEC template does not cover was named only in
a validation note; its amounts are now named and shown in the Results sheet
and the Legend.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from tests.run_q_support import make_pdf, scripted, template  # noqa: E402


def _run(pdf, tpl, answer):
    from extractor import run_extraction
    orch = scripted(answer)
    res = run_extraction(orch, pdf, tpl)
    return [r.extracted_data for r in res]


CHECK_LINES = [
    (40, 700, "Checks Paid"),
    (40, 680, "Number Date Amount Number Date Amount Number Date Amount"),
    (40, 660, "4416 07/08/19 $100.00 4419* 07/08/19 $266.00 4420 07/08/19 $69.13"),
    (40, 640, "4421 07/12/19 $12.53 4423 07/19/19 $114.00"),
]
FULL1 = "4416 07/08/19 $100.00 4419* 07/08/19 $266.00 4420 07/08/19 $69.13"
FULL2 = "4421 07/12/19 $12.53 4423 07/19/19 $114.00"


def _row(num, date, amt, source):
    return {"cells": {"Check Number": num, "Date": date, "Amount": amt},
            "source": source, "page": 1}


def _answer(rows):
    return {"fields": {}, "tables": {"Checks": rows}}


def _tpl():
    return template(tables=[("Checks", ["Check Number", "Date", "Amount"])],
                    doc_type="bank_statement")


class TestSideBySideRecords:
    def test_three_checks_on_one_line_are_three_rows(self, tmp_path):
        pdf = make_pdf(tmp_path / "checks.pdf", [CHECK_LINES])
        ed = _run(pdf, _tpl(), _answer([
            _row("4416", "07/08/19", "$100.00", FULL1),        # whole line
            _row("4419*", "07/08/19", "$266.00", "4419* 07/08/19 $266.00"),
            _row("4420", "07/08/19", "$69.13", "4420 07/08/19 $69.13"),
            _row("4421", "07/12/19", "$12.53", FULL2),
            _row("4423", "07/19/19", "$114.00", FULL2),
        ]))[0]
        rows = ed["Checks_rows"]
        assert [r["Check Number"] for r in rows] == ["4416", "4419*", "4420", "4421", "4423"]
        assert ed["validation"]["dropped_row_count"] == 0

    def test_the_same_record_twice_is_still_dropped(self, tmp_path):
        pdf = make_pdf(tmp_path / "checks.pdf", [CHECK_LINES])
        ed = _run(pdf, _tpl(), _answer([
            _row("4416", "07/08/19", "$100.00", FULL1),
            _row("4416", "07/08/19", "$100.00", FULL1),
        ]))[0]
        assert [r["Check Number"] for r in ed["Checks_rows"]] == ["4416"]
        assert ed["validation"]["dropped_row_count"] == 1

    def test_a_record_reusing_a_claimed_value_is_still_dropped(self, tmp_path):
        # the second row's check number and amount are the FIRST record's
        # words; nothing on the line is left for it
        pdf = make_pdf(tmp_path / "checks.pdf", [CHECK_LINES])
        ed = _run(pdf, _tpl(), _answer([
            _row("4421", "07/12/19", "$12.53", FULL2),
            _row("4421", "07/19/19", "$12.53", FULL2),
        ]))[0]
        assert ed["validation"]["dropped_row_count"] == 1


class TestAPageOfAmountsInNoCell:
    def test_named_as_a_completeness_reason(self, tmp_path):
        p1 = [(40, 700, "Account Summary"), (40, 680, "Opening Balance $1,000.00")]
        p2 = [(40, 700, "Line of Credit Summary"),
              (40, 680, "Previous Balance 926.18"), (40, 660, "Payments 13.17"),
              (40, 640, "New Balance 913.01"), (40, 620, "Credit Limit 1,000.00"),
              (40, 600, "Available Credit 86.99"), (40, 580, "Late Charges 0.54")]
        pdf = make_pdf(tmp_path / "two.pdf", [p1, p2])
        tpl = template(fields=["Opening Balance"], doc_type="bank_statement")
        from tests.run_q_support import slot_ids  # noqa: F401
        ans = {"fields": {"F1": {"value": "$1,000.00", "source": "Opening Balance $1,000.00",
                                 "page": 1, "status": "found"}}}
        ed = _run(pdf, tpl, ans)[0]
        texts = [a["text"] for a in ed["attention"]]
        hit = [t for t in texts if t.startswith("Page 2 prints")]
        assert hit, texts
        assert "926.18" in hit[0] and "913.01" in hit[0]
        assert any("Page 2" in s and "926.18" in s for s in ed.get("not_captured") or [])

    def test_a_page_whose_amounts_are_in_cells_says_nothing(self, tmp_path):
        p1 = [(40, 700, "Account Summary"), (40, 680, "Opening Balance $1,000.00"),
              (40, 660, "Closing Balance $1,200.00")]
        pdf = make_pdf(tmp_path / "one.pdf", [p1])
        tpl = template(fields=["Opening Balance", "Closing Balance"], doc_type="bank_statement")
        ans = {"fields": {
            "F1": {"value": "$1,000.00", "source": "Opening Balance $1,000.00", "page": 1},
            "F2": {"value": "$1,200.00", "source": "Closing Balance $1,200.00", "page": 1}}}
        ed = _run(pdf, tpl, ans)[0]
        assert not ed.get("not_captured")
        assert not any("prints" in a["text"] and "amounts" in a["text"]
                       for a in ed["attention"])


def _workbook(eds, tmp_path, grid):
    import openpyxl
    from app.models.models import DocumentResult
    from app.services.excel_slot import _write_excel
    from app.services.excel_cells import _add_review_legend
    from app.services.template_parsing import _analyse_template_regions
    docs = [DocumentResult(id=i, job_id=1, filename=f"doc{i}.pdf",
                           original_filename=f"doc{i}.pdf",
                           extraction_json=json.dumps(ed, default=str),
                           needs_review=True, reviewed=False)
            for i, ed in enumerate(eds, 1)]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    _write_excel(ws, docs, grid, _analyse_template_regions(grid), openpyxl)
    _add_review_legend(wb, docs)
    p = tmp_path / "out.xlsx"
    wb.save(p)
    return openpyxl.load_workbook(p)


def _texts(ws):
    return [str(c.value) for r in ws.iter_rows() for c in r if c.value is not None]


class TestShownInTheExport:
    def test_results_sheet_and_legend_carry_the_note(self, tmp_path):
        pdf = make_pdf(tmp_path / "one.pdf", [[(40, 700, "Opening Balance $1,000.00"),
                                               (40, 680, "Form 1099-K"),
                                               (40, 660, "1a Gross amount 8,525.00")]])
        tpl = template(fields=["Opening Balance"], doc_type="bank_statement")
        ans = {"fields": {"F1": {"value": "$1,000.00", "source": "Opening Balance $1,000.00",
                                 "page": 1}}}
        ed = _run(pdf, tpl, ans)[0]
        ed["not_captured"] = ["The document also prints Form 1099-K ... 8,525.00"]
        wb = _workbook([ed, ed], tmp_path, tpl["layout"])
        res = _texts(wb["Results"])
        assert sum(1 for t in res if t.startswith("Not in this file:") and "8,525.00" in t) == 2
        leg = _texts(wb["Legend"])
        assert any("Printed in the document but not in this file" in t for t in leg)
        assert sum(1 for t in leg if "8,525.00" in t) == 2


def _replay(job_id):
    import replay_raw
    if not replay_raw.has_raw(job_id):
        pytest.skip(f"local_docs/raw/{job_id} not present (git-ignored real data)")
    rep = replay_raw.replay_job(job_id)
    if not rep["docs"]:
        pytest.skip(f"job {job_id}: {rep['skipped']}")
    return rep


class TestRealJobs:
    def test_job_115_names_the_1099k_and_its_amounts(self, tmp_path):
        import openpyxl
        import replay_raw
        rep = _replay(115)
        _m, ed, _x = rep["docs"][0]
        nc = " ".join(ed.get("not_captured") or [])
        assert "1099-K" in nc and "8,525.00" in nc and "1,000.00" in nc
        p = replay_raw.write_workbook(115, rep, tmp_path / "j115.xlsx")
        wb = openpyxl.load_workbook(p)
        assert any("1099-K" in t and "8,525.00" in t for t in _texts(wb["Results"]))
        assert any("1099-K" in t and "8,525.00" in t for t in _texts(wb["Legend"]))

    def test_job_95_page_4_is_named(self):
        rep = _replay(95)
        _m, ed, _x = rep["docs"][0]
        texts = [a["text"] for a in ed["attention"]]
        hit = [t for t in texts if t.startswith("Page 4 prints")]
        assert hit, texts
        assert "913.01" in hit[0]
