"""Run Q, Q15 — tools/audit_exports.py counts what a reviewer would have to fix."""
from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import PatternFill

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import audit_exports as A  # noqa: E402


def _fill(c, argb):
    c.fill = PatternFill(fill_type="solid", fgColor=argb)


def _book(path, legend_low=1, legend_need=3):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"
    rows = [("Description", "Amount"), ("Coffee", 2.5), ("Tea", 3.0), ("Subtotal", 6.0),
            ("Total Invoices Count", 5), ("Phone", "YOUR PHONE"), ("Paid", "$2,750"),
            ("Box", "X"), ("Amount", "XX,XXX.00")]
    for r in rows:
        ws.append(r)
    _fill(ws["B2"], "FFFFC7CE")                     # low
    _fill(ws["B3"], "FFFFEB9C")                     # amber
    _fill(ws["B6"], "FFD9D9D9")                     # grey
    _fill(ws["B7"], "FFE2EFDA")
    ws["B7"].comment = Comment("REVIEWED by a person. Machine status was Low: x", "t")
    lg = wb.create_sheet("Legend")
    lg.append(("Document", "Values", "Need review", "Low", "Unverified", "Empty, flagged",
               "Needs attention"))
    lg.append(("a.pdf", 8, legend_need, legend_low, 1, 1, 0))
    wb.save(path)
    return path


def test_counts_every_mark_and_problem(tmp_path):
    r = A.audit_file(_book(tmp_path / "a.xlsx"))
    assert (r["low"], r["amber"], r["grey"], r["accepted"]) == (1, 1, 1, 1)
    assert r["placeholder"] == 2                     # YOUR PHONE, XX,XXX.00 -- never a bare X
    assert r["money_text"] == 1                      # "$2,750"
    assert r["sum_off"] and "6" in r["sum_off"][0] and "5.50" in r["sum_off"][0]
    assert r["legend_off"] == []
    assert r["count_off"] and "prints 5" in r["count_off"][0]


def test_legend_disagreement_is_reported(tmp_path):
    r = A.audit_file(_book(tmp_path / "b.xlsx", legend_low=4, legend_need=9))
    assert any("Legend Low 4 vs 1" in x for x in r["legend_off"])
    assert any("Need review 9 vs 3" in x for x in r["legend_off"])


def test_folder_scan_is_read_only(tmp_path):
    p = _book(tmp_path / "c.xlsx")
    before = p.read_bytes()
    rows = A.audit(tmp_path)
    assert len(rows) == 1 and p.read_bytes() == before
    assert "TOTAL (1 files)" in A.render(rows)
