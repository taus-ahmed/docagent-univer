"""B4 — the Legend and the cells agree, and an empty-flagged cell is grey with
a comment in the default (clean) download.

Before: of the 16 real staging exports, jobs 46, 48 and 51 disagreed — job 48
said "12 empty and flagged, 5 low" and showed 5 red cells and no grey one —
because the slot writer marked only slots holding a value. The real exports
are measured by `tests.legend_check` (python -m tests.legend_check
local_docs/batch1_exports); here the CURRENT writer's output for the same
documents is checked.
"""

from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace

import openpyxl
import pytest

from tests import legend_check as L
from tests import overnight_helpers as H
from tests.test_overnight_a1_a2 import PITT, pitt_answer, pitt_grid
from tests.test_overnight_a4 import MAMMOTH, mammoth_fields, mammoth_grid, mammoth_rows


def _workbook(records, grid):
    from app.api.routes import extract as X
    wb = openpyxl.Workbook()
    docs = [SimpleNamespace(filename=name, get_extracted_data=lambda d=d: d)
            for name, d in records]
    with contextlib.redirect_stdout(io.StringIO()):
        X._write_excel(wb.active, docs, grid, {}, openpyxl)   # default download
        X._add_review_legend(wb, docs)
    return wb


def _pitt_with_empty_flags():
    g = pitt_grid()
    a = pitt_answer(g)
    # leave two printed boxes out: the gate flags them empty
    for label in ("Box 1 Wages Tips Other Compensation", "Box 2 Federal Income Tax Withheld"):
        a["fields"].pop(H.field_id(g, label))
    return g, H.run(PITT, g, a, doc_type="w2")[0]


def _mammoth_page_one_only():
    g = mammoth_grid()
    name = H.table_name(g, "Transactions")
    a = {"fields": {}, "tables": {name: mammoth_rows(1)}}
    return g, H.run(MAMMOTH, g, a, doc_type="bank_statement",
                    answers=[a, {"fields": {}, "tables": {name: []}}])[0]


CASES = {"pitt_empty_flags": _pitt_with_empty_flags,
         "mammoth_page_one_only": _mammoth_page_one_only}


@pytest.mark.parametrize("case", sorted(CASES))
def test_legend_counts_equal_the_marked_cells(case):
    g, data = CASES[case]()
    wb = _workbook([("doc.pdf", data)], g)
    assert L.check(wb) == []
    assert L.legend_counts(wb).get("empty_flagged", 0) == L.cell_counts(wb)["grey"]


def test_an_empty_flagged_slot_is_grey_with_a_comment():
    g, data = _mammoth_page_one_only()
    flagged = {f["ref"] for f in H.flags(data) if "empty_flagged" in f["reason"]}
    assert {"Opening Balance", "Closing Balance"} <= flagged, H.flags(data)
    ws = _workbook([("mammoth_2pg.pdf", data)], g).worksheets[0]
    for label in ("Opening Balance", "Closing Balance"):
        r = next(c.row for c in ws["A"] if c.value == label)
        cell = ws.cell(r, 2)
        assert cell.value in (None, "")
        assert cell.fill.fgColor.rgb == L.GREY
        assert cell.comment and "NEEDS REVIEW" in cell.comment.text


def test_a_combined_export_agrees_too():
    g, a = _pitt_with_empty_flags()
    _g2, b = _mammoth_page_one_only()
    wb = _workbook([("pitt_sample_w2.pdf", a), ("pitt_again.pdf", a)], g)
    assert L.check(wb) == []
    g2, _b = _mammoth_page_one_only()
    wb = _workbook([("mammoth_2pg.pdf", b), ("mammoth_again.pdf", b)], g2)
    assert L.check(wb) == []
