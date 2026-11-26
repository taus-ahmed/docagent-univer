"""Run R, R1 — a grouped table keeps its group lines and subtotals.

Job 131 (mobile_vendor_list_8pg, no template): 31 vendor lines
("300055 ANDERSON DULANEY") and 14 vendor subtotals printed between the
invoice rows, none of them in the export. The unit tests use lines shaped
like the real page; the `_real` tests replay the stored answer and skip when
local_docs is absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import row_groups as RG  # noqa: E402


def _line(text, page=1, y=0):
    out, x = [], 10.0
    for t in text.split():
        out.append({"text": t, "x0": x, "x1": x + 6 * len(t), "top": y,
                    "bottom": y + 8, "page": page})
        x += 6 * len(t) + 4
    return out


HEAD = "INVOICE P.O. INV DATE CHECK RUN CHECK # INVOICE NET PAID AMOUNT DUE DATE TYPE STS DESCR"


def _page(n, body):
    return [_line(t, n) for t in ["City of Mobile", "VENDOR INVOICE LIST", HEAD] + body
            + [f"Report generated: 06/24/2026 14:36 Page {n}"]]


PAGE1 = _page(1, [
    "300055 ANDERSON DULANEY",
    "0025 06/22/2026 H062426 20218284 75.00 75.00 07/22/2026 INV PD STRING",
    "CHECK DATE: 06/24/2026",
    "299694 B&B LAWN/LANDSCAPING",
    "2937 06/16/2026 H062426 917846 2,480.00 2,480.00 07/16/2026 INV PD Right",
    "CHECK DATE: 06/24/2026",
    "2938 06/17/2026 H062426 917846 2,400.00 2,400.00 07/17/2026 INV PD Right",
    "CHECK DATE: 06/24/2026",
    "4,880.00",
    "295877 DAUGHTRY'S LAWN CARE LLC",          # rows on the NEXT page
])
PAGE2 = _page(2, [
    "6150 06/01/2026 H062426 917850 100.00 100.00 07/01/2026 INV PD MOW",
    "CHECK DATE: 06/24/2026",
    "6151 06/02/2026 H062426 917850 50.00 50.00 07/02/2026 INV PD MOW",
    "CHECK DATE: 06/24/2026",
    "150.00",
    "6 INVOICES 5,105.00",
])


def _lines():
    return PAGE1 + PAGE2


class TestDetect:
    def test_groups_and_subtotals_found(self):
        g = RG.detect(_lines())
        assert g is not None
        assert [x.label for x in g.groups] == [
            "300055 ANDERSON DULANEY", "299694 B&B LAWN/LANDSCAPING",
            "295877 DAUGHTRY'S LAWN CARE LLC"]
        assert [x.subtotal for x in g.groups] == [None, "4,880.00", "150.00"]
        assert g.grand_total == "5,105.00"

    def test_a_group_line_at_the_foot_of_a_page_owns_the_next_pages_rows(self):
        g = RG.detect(_lines())
        assert len(g.groups[2].rows) == 2

    def test_one_coincidental_sum_is_not_a_grouped_table(self):
        # a Closing Disclosure: one bare amount that happens to sum the lines
        # above it, under a label line - not a grouped table
        lines = [_line(t) for t in [
            "Costs at Closing", "Closing Costs 9,712.10 includes 4,694.05",
            "Other Costs 5,018.05 more fees here", "9,712.10",
            "Cash to Close", "Down payment 18,000.00 and the rest"]]
        assert RG.detect(lines) is None

    def test_label_lines_without_any_reconciling_total_are_not_groups(self):
        lines = [_line(t) for t in [
            "ACME SUPPLY CO", "1 Widget 2 10.00 20.00 ok",
            "BETA TRADING", "2 Gadget 1 5.00 5.00 ok", "99.00"]]
        assert RG.detect(lines) is None

    def test_group_noun_from_the_title(self):
        assert RG.group_noun(_lines()) == "Vendor"
        assert RG.group_noun([_line("Monthly report")]) == "Group"


class TestInferredColumn:
    def test_the_widest_table_gets_the_group_column_first(self):
        # Run S, 1b: the group line's identifier and name are two columns
        # (was one `Vendor` column holding the whole line)
        inf = {"tables": [{"name": "Invoice List", "columns": ["INVOICE", "INVOICE NET"]}]}
        assert RG.add_group_column(inf, [PAGE1, PAGE2]) == ["Vendor ID", "Vendor Name"]
        assert inf["tables"][0]["columns"] == ["Vendor ID", "Vendor Name", "INVOICE",
                                               "INVOICE NET"]

    def test_an_ungrouped_document_is_unchanged(self):
        inf = {"tables": [{"name": "T", "columns": ["A", "B"]}]}
        assert RG.add_group_column(inf, [[_line("Hello world")]]) is None
        assert inf["tables"][0]["columns"] == ["A", "B"]


class TestApply:
    def _rows(self):
        lines = _lines()
        g = RG.detect(lines)
        rows, where = [], {}
        for i, ln in enumerate(lines):
            if RG._kind(ln) == "row":
                toks = [w["text"] for w in ln]
                r = {"Vendor": "", "INVOICE": toks[0], "INVOICE NET": toks[4],
                     "PAID AMOUNT": toks[5]}
                rows.append(r)
                where[id(r)] = i
        return g, rows, where

    def test_every_row_gets_its_vendor_and_each_subtotal_a_row(self):
        g, rows, where = self._rows()
        subs, flags, notes = RG.apply(rows, where, g, "Vendor",
                                      ["Vendor", "INVOICE", "INVOICE NET", "PAID AMOUNT"],
                                      "grounded", "low")
        assert [r["Vendor"] for r in rows] == [
            "300055 ANDERSON DULANEY", "299694 B&B LAWN/LANDSCAPING",
            "299694 B&B LAWN/LANDSCAPING", "295877 DAUGHTRY'S LAWN CARE LLC",
            "295877 DAUGHTRY'S LAWN CARE LLC"]
        assert [(s["Vendor"], s["INVOICE"], s["INVOICE NET"]) for s in subs] == [
            ("299694 B&B LAWN/LANDSCAPING", "Subtotal", "4,880.00"),
            ("295877 DAUGHTRY'S LAWN CARE LLC", "Subtotal", "150.00")]
        assert all(s["_confidence"] == "grounded" and s["_subtotal"] for s in subs)
        assert not flags
        assert any("grand total 5,105.00 equals" in n for n in notes)

    def test_a_subtotal_that_does_not_add_up_is_low_and_flagged(self):
        g, rows, where = self._rows()
        rows[1]["INVOICE NET"] = "2,000.00"          # model misread one row,
        rows[1]["PAID AMOUNT"] = "2,000.00"          # in both money columns
        subs, flags, _n = RG.apply(rows, where, g, "Vendor",
                                   ["Vendor", "INVOICE", "INVOICE NET", "PAID AMOUNT"],
                                   "grounded", "low")
        assert subs[0]["_confidence"] == "low"
        assert any("does not equal the sum" in f[2] and "B&B" in f[2] for f in flags)
        assert any("grand total" in f[0] for f in flags)

    def test_the_writer_puts_each_subtotal_after_its_groups_last_row(self):
        g, rows, where = self._rows()
        subs, _f, _n = RG.apply(rows, where, g, "Vendor",
                                ["Vendor", "INVOICE", "INVOICE NET"], "grounded", "low")
        ed = {"T_rows": rows, "T_subtotals": subs, "T_group_key": "Vendor"}
        out = RG.rows_with_subtotals(ed, "T")
        assert [r["INVOICE"] for r in out] == [
            "0025", "2937", "2938", "Subtotal", "6150", "6151", "Subtotal"]


def _replay(job_id):
    import replay_raw
    if not replay_raw.has_raw(job_id):
        pytest.skip(f"local_docs/raw/{job_id} not present (git-ignored real data)")
    rep = replay_raw.replay_job(job_id)
    if not rep["docs"]:
        pytest.skip(f"job {job_id}: {rep['skipped']}")
    return rep


class TestJob131Real:
    def test_vendors_and_subtotals_reach_the_export(self, tmp_path):
        import replay_raw
        rep = _replay(131)
        _m, ed, _x = rep["docs"][0]
        name = next(t["name"] for t in ed["slot_map"]["tables"])
        rows = ed[f"{name}_rows"]
        assert len(rows) == 90
        # Run S, 1b: identifier and name in two columns, both on every row
        assert ed.get(f"{name}_group_key") == "Vendor ID"
        vendors = {(r["Vendor ID"], r["Vendor Name"]) for r in rows}
        assert len(vendors) == 31
        assert all(r["Vendor ID"] and r["Vendor Name"] for r in rows)
        assert ("300055", "ANDERSON DULANEY") in vendors
        subs = ed[f"{name}_subtotals"]
        assert len(subs) == 14
        assert all(s["_confidence"] != "low" for s in subs)
        assert any("grand total 237,183.08 equals" in n for n in ed["validation_notes"])
        # and the workbook holds them, each subtotal under its vendor's rows
        import openpyxl
        p = replay_raw.write_workbook(131, rep, tmp_path / "job_131.xlsx")
        ws = openpyxl.load_workbook(p).worksheets[0]
        cells = [[c.value for c in r] for r in ws.iter_rows()]
        flat = [str(v) for r in cells for v in r if v is not None]
        assert "300055" in flat and "ANDERSON DULANEY" in flat
        assert sum(1 for v in flat if v == "Subtotal") == 14
        i = next(k for k, r in enumerate(cells) if "4,880.00" in [str(v) for v in r]
                 or 4880.0 in r)
        assert "Subtotal" in [str(v) for v in cells[i]]
        assert "B&B LAWN/LANDSCAPING" in [str(v) for v in cells[i]]
        assert "299694" in [str(v) for v in cells[i]]
