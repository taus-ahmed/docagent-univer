"""Run C — the downloaded file must be right.

C1 block layout · C2 clean default download · C3 numbers are numbers ·
C4 duplicate total rows and the missing invoice totals block.

Every workbook here is built by the real writer from a stored-result-shaped
dict, saved, and READ BACK with openpyxl; the samples are left in tests/out/
(git-ignored) so a person can open them.
"""
from __future__ import annotations

import contextlib
import io
import json
from numbers import Number
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import openpyxl  # noqa: E402

OUT = bs.REPO_DIR / "tests" / "out"


# ── fixtures: a stored result built from the template's own slots ─────────────

def stored(grid, fields=None, rows=None, conf=None, extra=None):
    """A slot-path stored result for `grid`: field values by row label, table
    rows by band name, every value grounded at `conf` (default high)."""
    from slot_extractor import _table_map, enumerate_slots
    slots = enumerate_slots(grid)
    fields, rows, conf = fields or {}, rows or {}, conf or {}
    ef, prov, cmap = {}, {}, {}
    for f in slots["fields"]:
        if f["row_label"] in fields:
            v = fields[f["row_label"]]
            ef[f["ref"]] = v
            prov[f["ref"]] = {"source": f'{f["row_label"]} {v}', "page": 1,
                              "grounded": True}
            cmap[f["ref"]] = conf.get(f["row_label"], "high")
    ed = {"template_type": "slot", "extracted_fields": ef,
          "field_provenance": prov,
          "validation": {"confidence_map": cmap, "flagged_fields": []},
          "slot_map": {"fields": [{k: f[k] for k in ("slot_id", "ref", "row_label",
                                                      "section")}
                                  for f in slots["fields"]],
                       "tables": [_table_map(t) for t in slots["tables"]]},
          "table_rows": []}
    for t in slots["tables"]:
        key = "table_rows" if t["name"] == "table" else f'{t["name"]}_rows'
        ed[key] = [{**r, "_confidence": "high", "_source": " ".join(
            str(v) for v in r.values()), "_page": 1}
            for r in rows.get(t["name"], [])]
    ed.update(extra or {})
    return ed, slots


def doc(ed, filename):
    s = json.dumps(ed, default=str)
    return SimpleNamespace(id=1, filename=filename, document_type="x",
                           overall_confidence="high", needs_review=False,
                           get_extracted_data=lambda: json.loads(s))


def export(docs, grid, name, **kw):
    """The workbook as the download route writes it (defaults: a clean file),
    saved to tests/out/<name>.xlsx and read back."""
    from app.api.routes.extract import _add_review_legend, _write_excel
    wb = openpyxl.Workbook()
    wb.active.title = "Results"
    with contextlib.redirect_stdout(io.StringIO()):
        _write_excel(wb.active, docs, grid, None, openpyxl, **kw)
        _add_review_legend(wb, docs)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.xlsx"
    wb.save(path)
    return openpyxl.load_workbook(path), path


def grid_of(rows):
    """{(r, c): text} -> a SheetSaveData grid."""
    return {"cells": {f"{r},{c}": {"value": v} for (r, c), v in rows.items()},
            "colWidths": [], "merges": {}}


def col_a(ws):
    return {c.row: c.value for c in ws["A"] if c.value not in (None, "")}


def blocks(ws, title):
    """1-based first rows of each document block (its title row)."""
    return [r for r, v in col_a(ws).items() if v == title]


def last_used_row(ws, lo, hi):
    return max(c.row for row in ws.iter_rows(min_row=lo, max_row=hi)
               for c in row if c.value not in (None, ""))


def assert_block_frame(ws, starts, title):
    """Every block: a header strip on its first row naming its file, a thick
    bottom border under its last row, exactly 3 blank rows to the next."""
    from app.services.excel_slot import GAP_BETWEEN_DOCS
    assert GAP_BETWEEN_DOCS == 3
    ends = []
    for i, s in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else ws.max_row + 1
        end = last_used_row(ws, s, nxt - 1)
        ends.append(end)
        a = ws.cell(s, 1)
        assert a.value == title and a.font.b and a.border.top.style == "thick"
        strip = [ws.cell(s, c).value for c in range(1, ws.max_column + 1)]
        assert any(isinstance(v, str) and ".pdf" in v for v in strip), strip
        if i + 1 < len(starts):
            assert nxt - end - 1 == 3, (s, end, nxt)
            assert all(ws.cell(r, c).value in (None, "")
                       for r in range(end + 1, nxt)
                       for c in range(1, ws.max_column + 1))
    return ends


# ══════════════════════════════════════════════════════════════════════════
# C1 — block layout
# ══════════════════════════════════════════════════════════════════════════

PAYSLIP = grid_of({
    (0, 0): "PAYSLIP",
    (1, 0): "Employee", (2, 0): "Pay Date",
    (4, 0): "Earning", (4, 1): "Hours", (4, 2): "Amount",          # rows 5-14 reserved
    (15, 0): "Total Earnings",
    # row 16 blank, BY DESIGN — between Total Earnings and Deductions
    (17, 0): "Deduction", (17, 1): "Current", (17, 2): "YTD",       # rows 18-27 reserved
    (28, 0): "Total Deductions",
    # row 29 blank, BY DESIGN — before Net Pay
    (30, 0): "Net Pay",
})


def _payslip(n_earn, n_ded, name):
    earn = [{"Earning": f"E{i}", "Hours": "8", "Amount": f"{100 + i}.00"}
            for i in range(n_earn)]
    ded = [{"Deduction": f"D{i}", "Current": f"{10 + i}.00", "YTD": f"{40 + i}.00"}
           for i in range(n_ded)]
    from slot_extractor import enumerate_slots
    t1, t2 = (t["name"] for t in enumerate_slots(PAYSLIP)["tables"])
    ed, slots = stored(PAYSLIP, {"Employee": name, "Pay Date": "2026-04-30",
                                 "Total Earnings": "999.00",
                                 "Total Deductions": "111.00",
                                 "Net Pay": "888.00"},
                       {t1: earn, t2: ded})
    return ed, slots


class TestC1BlockLayout:
    def test_the_payslip_template_has_its_totals_outside_the_bands(self):
        """C4.2's shape fix is what lets a single `Total Earnings` under the
        reserved rows be a slot rather than a row label inside the band."""
        _ed, slots = _payslip(1, 1, "x")
        labels = {f["row_label"] for f in slots["fields"]}
        assert {"Total Earnings", "Total Deductions", "Net Pay"} <= labels
        bands = [(t["start_row"], t["end_row"]) for t in slots["tables"]]
        assert bands == [(5, 14), (18, 27)], bands

    @pytest.mark.parametrize("counts", [((2, 8), (3, 9))])
    def test_two_payslips_with_different_line_counts(self, counts):
        docs = []
        for i, (ne, nd) in enumerate(counts, 1):
            ed, _ = _payslip(ne, nd, f"Employee {i}")
            docs.append(doc(ed, f"payslip_{i}.pdf"))
        wb, _path = export(docs, PAYSLIP, "c1_payslips_2-8_vs_3-9")
        ws = wb["Results"]
        starts = blocks(ws, "PAYSLIP")
        assert len(starts) == 2
        ends = assert_block_frame(ws, starts, "PAYSLIP")
        for s, (ne, nd) in zip(starts, counts):
            a = col_a(ws)
            assert a[s + 4] == "Earning"
            assert [a[s + 5 + i] for i in range(ne)] == [f"E{i}" for i in range(ne)]
            te = s + 5 + ne
            assert a[te] == "Total Earnings"                # directly under the last row
            assert ws.cell(te, 2).value == 999.0
            assert te + 1 not in a                          # the template's own blank row
            assert a[te + 2] == "Deduction"
            assert [a[te + 3 + i] for i in range(nd)] == [f"D{i}" for i in range(nd)]
            td = te + 3 + nd
            assert a[td] == "Total Deductions" and td + 1 not in a
            assert a[td + 2] == "Net Pay" and ws.cell(td + 2, 2).value == 888.0
        assert all(ws.cell(e, 1).border.bottom.style == "thick" for e in ends)

    def test_no_reserved_row_is_invented(self):
        ed, _ = _payslip(2, 8, "Only two")
        ws = export([doc(ed, "two.pdf")], PAYSLIP, "c1_payslip_two_lines")[0]["Results"]
        a = col_a(ws)
        import re
        earn = [v for v in a.values() if re.fullmatch(r"E\d+", str(v))]
        assert earn == ["E0", "E1"]                         # 2 lines, not 10

    def test_three_invoices_with_1_3_and_8_lines(self):
        from tests.contract.run_a_driver import template_grid
        grid = template_grid("AP_Inv_Full")
        docs = []
        for i, n in enumerate((1, 3, 8), 1):
            lines = [{"Line": str(k + 1), "Description": f"Item {i}.{k + 1}",
                      "Quantity": "1", "Unit Price": "10.00",
                      "Line Amount": "10.00"} for k in range(n)]
            ed, _ = stored(grid, {"Vendor Name": f"Vendor {i}",
                                  "Invoice Number": f"INV-{i:03d}",
                                  "Subtotal": f"{10 * n}.00",
                                  "Tax Total": f"{2 * n}.00",
                                  "Invoice Total": f"{12 * n}.00"},
                           {"table": lines})
            docs.append(doc(ed, f"invoice_{n}_lines.pdf"))
        ws = export(docs, grid, "c1_invoices_1_3_8")[0]["Results"]
        starts = blocks(ws, "Vendor Name")
        assert len(starts) == 3
        assert_block_frame(ws, starts, "Vendor Name")
        for s, n, i in zip(starts, (1, 3, 8), (1, 2, 3)):
            a = col_a(ws)
            first = s + 14                                  # template row 15
            assert [a[first + k] for k in range(n)] == list(range(1, n + 1))  # a count: a number
            sub = first + n
            assert a[sub] == "Subtotal" and ws.cell(sub, 2).value == 10.0 * n
            assert a[sub + 3] == "Tax Total" and ws.cell(sub + 3, 2).value == 2.0 * n
            assert a[sub + 4] == "Invoice Total" and ws.cell(sub + 4, 2).value == 12.0 * n
            strip = " ".join(str(ws.cell(s, c).value or "") for c in range(1, 8))
            assert f"invoice_{n}_lines.pdf" in strip and f"INV-{i:03d}" in strip

    def test_a_bank_statement_with_two_bands(self):
        grid = grid_of({
            (0, 0): "STATEMENT", (1, 0): "Account Number",
            (3, 0): "Date", (3, 1): "Description", (3, 2): "Deposit",
            (10, 0): "Total Deposits",
            (12, 0): "Date", (12, 1): "Description", (12, 2): "Withdrawal",
            (19, 0): "Total Withdrawals",
            (21, 0): "Closing Balance"})
        from slot_extractor import enumerate_slots
        names = [t["name"] for t in enumerate_slots(grid)["tables"]]
        assert len(names) == 2, names
        deps = [{"Date": f"01/0{k + 1}", "Description": f"dep {k}", "Deposit": "5.00"}
                for k in range(2)]
        wds = [{"Date": f"01/1{k}", "Description": f"wd {k}", "Withdrawal": "1.00"}
               for k in range(4)]
        ed, _ = stored(grid, {"Account Number": "000123", "Total Deposits": "10.00",
                              "Total Withdrawals": "4.00", "Closing Balance": "6.00"},
                       {names[0]: deps, names[1]: wds})
        ws = export([doc(ed, "stmt.pdf"), doc(ed, "stmt2.pdf")], grid,
                    "c1_bank_two_bands")[0]["Results"]
        starts = blocks(ws, "STATEMENT")
        assert_block_frame(ws, starts, "STATEMENT")
        s, a = starts[0], col_a(ws)
        assert a[s + 6] == "Total Deposits"                 # 2 rows under the header
        assert a[s + 8] == "Date" and a[s + 13] == "Total Withdrawals"
        assert a[s + 15] == "Closing Balance"
        assert ws.cell(s + 1, 2).value == "000123"          # an identifier stays text

    def test_a_balance_sheet(self):
        grid = json.loads((bs.TEMPLATES_DIR / "balance_sheet.json").read_text(
            encoding="utf-8"))
        grid = grid.get("grid", grid)
        from slot_extractor import enumerate_slots
        slots = enumerate_slots(grid)
        rows = {t["name"]: [{c.get("key") or c["header"]: (f"{t['name']} {k}" if j == 0
                             else f"{100 * (k + 1)}")
                             for j, c in enumerate(t["columns"])} for k in range(2)]
                for t in slots["tables"]}
        fields = {f["row_label"]: "1,000" for f in slots["fields"]}
        ed, _ = stored(grid, fields, rows)
        wb, _path = export([doc(ed, "bs_a.pdf"), doc(ed, "bs_b.pdf")], grid,
                           "c1_balance_sheet")
        ws = wb["Results"]
        title = col_a(ws)[1]
        starts = blocks(ws, title)
        assert len(starts) == 2
        assert_block_frame(ws, starts, title)
        # every band holds exactly its 2 rows, and nothing overlaps: each
        # band's rows are followed directly by the next template content
        a = col_a(ws)
        for t in slots["tables"]:
            got = [r for r, v in a.items() if str(v).startswith(f"{t['name']} ")]
            assert len(got) == 4, (t["name"], got)          # 2 per document

    def test_review_marks_follow_the_moved_rows(self):
        """A low total moved up by the compaction carries its own fill."""
        ed, _ = _payslip(2, 2, "x")
        ref = next(f["ref"] for f in ed["slot_map"]["fields"]
                   if f["row_label"] == "Total Deductions")
        ed["validation"]["confidence_map"][ref] = "low"
        ws = export([doc(ed, "low.pdf")], PAYSLIP, "c1_marks_follow")[0]["Results"]
        r = next(r for r, v in col_a(ws).items() if v == "Total Deductions")
        cell = ws.cell(r, 2)
        assert cell.value == 111.0
        assert cell.fill.fgColor.rgb == "FFFFC7CE" and cell.comment is not None


# ══════════════════════════════════════════════════════════════════════════
# C2 — the default download holds only the template's own fields
# ══════════════════════════════════════════════════════════════════════════

class TestC2CleanDefault:
    def _two(self):
        ed, _ = _payslip(2, 3, "x")
        ref = next(f["ref"] for f in ed["slot_map"]["fields"]
                   if f["row_label"] == "Net Pay")
        ed["validation"]["confidence_map"][ref] = "low"
        return [doc(ed, "a.pdf")]

    def _texts(self, ws):
        return [str(c.value) for row in ws.iter_rows() for c in row if c.value]

    def test_default_has_no_audit_columns_but_keeps_fills_comments_legend(self):
        wb, _ = export(self._two(), PAYSLIP, "c2_default")
        ws = wb["Results"]
        texts = self._texts(ws)
        assert not any(t.startswith("Review status") or t == "Source"
                       or " · p." in t for t in texts), texts
        assert ws.max_column <= 4                           # A:C + the strip label
        assert any(c.fill.fgColor.rgb == "FFFFC7CE" for row in ws.iter_rows()
                   for c in row)
        assert any(c.comment for row in ws.iter_rows() for c in row)
        assert "Legend" in wb.sheetnames
        assert "need" in str(wb["Legend"]["A1"].value)

    def test_include_audit_brings_both_back(self):
        wb, _ = export(self._two(), PAYSLIP, "c2_include_audit", audit=True)
        texts = self._texts(wb["Results"])
        assert any(t.startswith("Review status") for t in texts)
        assert any(" · p." in t for t in texts)


# ══════════════════════════════════════════════════════════════════════════
# C3 — numbers are numbers, at every review state; identifiers stay text
# ══════════════════════════════════════════════════════════════════════════

C3_GRID = grid_of({(i, 0): lab for i, lab in enumerate([
    "Verified", "Grounded", "Unverified", "Low", "Edited", "Accepted",
    "Negative", "Trailing Minus", "Indian", "Zero",
    "Code", "Routing Number", "Invoice Number", "Date", "SSN", "Last 4",
    "Edited Note", "Check #"])})


class TestC3NumbersAreNumbers:
    VALUES = {
        "Verified": "$1,234.50", "Grounded": "1,234.50", "Unverified": "1,234.50",
        "Low": "1,234.50", "Edited": "1,234.50", "Accepted": "1,234.50",
        "Negative": "(1,234.50)", "Trailing Minus": "1,234.50-",
        "Indian": "₹1,23,456.78", "Zero": "0",
        "Code": "007", "Routing Number": "021000021",
        "Invoice Number": "INV-2024-0031", "Date": "01/15/2024",
        "SSN": "XXX-XX-1234", "Last 4": "1234", "Edited Note": "see attached",
        "Check #": "123456"}
    CONF = {"Grounded": "grounded", "Unverified": "unverified", "Low": "low",
            "Edited": "edited", "Accepted": "low", "Edited Note": "edited"}

    @pytest.fixture(scope="class")
    def ws(self):
        ed, _ = stored(C3_GRID, self.VALUES, conf=self.CONF)
        by = {f["row_label"]: f["ref"] for f in ed["slot_map"]["fields"]}
        ed["field_provenance"][by["Accepted"]]["reviewed"] = {"by": "x", "at": "t"}
        for lab in ("Edited", "Edited Note"):
            ed["field_provenance"][by[lab]]["edited"] = True
        wb, _ = export([doc(ed, "c3.pdf")], C3_GRID, "c3_numbers")
        ws = wb["Results"]
        return {ws.cell(r, 1).value: ws.cell(r, 2) for r in range(1, ws.max_row + 1)
                if ws.cell(r, 1).value}

    @pytest.mark.parametrize("label", ["Verified", "Grounded", "Unverified", "Low",
                                       "Edited", "Accepted"])
    def test_every_review_state_writes_a_number(self, ws, label):
        c = ws[label]
        assert isinstance(c.value, Number) and c.value == 1234.5, (label, c.value)
        assert c.data_type == "n"

    def test_confidence_changes_the_fill_not_the_type(self, ws):
        assert ws["Low"].fill.fgColor.rgb == "FFFFC7CE"
        assert ws["Edited"].fill.fgColor.rgb == "FFE4DFEC"
        assert ws["Verified"].fill.fgColor.rgb not in ("FFFFC7CE", "FFE4DFEC")

    def test_notation_survives_as_a_number_format(self, ws):
        assert ws["Verified"].number_format == '"$"#,##0.00'
        assert ws["Negative"].number_format == "#,##0.00_);(#,##0.00)"

    def test_negatives_and_indian_grouping(self, ws):
        assert ws["Negative"].value == -1234.5
        assert ws["Trailing Minus"].value == -1234.5
        assert ws["Indian"].value == 123456.78

    def test_zero_is_a_value(self, ws):
        assert ws["Zero"].value == 0 and ws["Zero"].data_type == "n"

    @pytest.mark.parametrize("label,text", [
        ("Code", "007"), ("Routing Number", "021000021"),
        ("Invoice Number", "INV-2024-0031"),
        ("SSN", "XXX-XX-1234"), ("Last 4", "1234"), ("Check #", "123456")])
    def test_identifiers_stay_text(self, ws, label, text):
        assert ws[label].value == text and ws[label].data_type == "s", label

    def test_an_unambiguous_date_is_a_real_date(self, ws):
        # Run G, G6 (owner ruling): 01/15/2024 has one meaning, so it is a
        # date cell holding exactly 15 January 2024, shown mm/dd/yyyy.
        from datetime import datetime
        assert ws["Date"].is_date and ws["Date"].value == datetime(2024, 1, 15)
        assert ws["Date"].number_format == "mm/dd/yyyy"

    def test_an_edited_value_that_does_not_parse_stays_text_and_lavender(self, ws):
        c = ws["Edited Note"]
        assert c.value == "see attached" and c.data_type == "s"
        assert c.fill.fgColor.rgb == "FFE4DFEC"


# ══════════════════════════════════════════════════════════════════════════
# C4 — duplicate total rows; the missing invoice totals block
# ══════════════════════════════════════════════════════════════════════════

INVOICE = grid_of({
    (0, 0): "INVOICE", (1, 0): "Invoice Number",
    (3, 0): "Description", (3, 1): "Qty", (3, 2): "Amount",
    (10, 0): "Subtotal", (11, 0): "Tax", (12, 0): "Total"})


class TestC4DuplicateTotals:
    def _answer(self, total_row_amount):
        from slot_extractor import enumerate_slots
        slots = enumerate_slots(INVOICE)
        ids = {f["row_label"]: f["slot_id"] for f in slots["fields"]}
        name = slots["tables"][0]["name"]
        fields = {ids["Invoice Number"]: ("INV-7", "Invoice Number INV-7"),
                  ids["Subtotal"]: ("$30.00", "Subtotal $30.00"),
                  ids["Tax"]: ("$3.00", "Tax $3.00"),
                  ids["Total"]: ("$33.00", "Total $33.00")}
        # a TOTAL line returned as a row. Its amount is not the sum of the
        # rows above it (30), so the Part 3.5 total-row gate leaves it alone;
        # only the slot below the table says it is a duplicate.
        rows = [({"Description": "Pens", "Qty": "1", "Amount": "$10.00"}, "Pens 1 $10.00"),
                ({"Description": "Ink", "Qty": "2", "Amount": "$20.00"}, "Ink 2 $20.00"),
                ({"Description": "Total", "Qty": "", "Amount": total_row_amount},
                 f"Total {total_row_amount}")]
        text = "\n".join(["INVOICE", "Invoice Number INV-7", "Description Qty Amount",
                          "Pens 1 $10.00", "Ink 2 $20.00", f"Total {total_row_amount}",
                          "Subtotal $30.00", "Tax $3.00", "Total $33.00"])
        answer = {"fields": {sid: {"value": v, "source": s, "page": 1}
                             for sid, (v, s) in fields.items()},
                  "tables": {name: [{"cells": c, "source": s, "page": 1}
                                    for c, s in rows]}}
        return answer, text, name

    def _extract(self, amount):
        from tests.contract.run_a_driver import model_response
        from slot_extractor import run_slot_extraction
        answer, text, name = self._answer(amount)
        llm = SimpleNamespace(extract=lambda **k: model_response(answer))
        with contextlib.redirect_stdout(io.StringIO()):
            res = run_slot_extraction(
                SimpleNamespace(llm=llm), Path("inv.pdf"), {"layout": INVOICE},
                None, page_images=[], doc_text=text, doc_text_pages=[text],
                file_type="digital_pdf", default_doc_type="invoice", start=0.0)[0]
        ed = res.extracted_data
        key = "table_rows" if name == "table" else f"{name}_rows"
        return ed, ed[key]

    def test_a_matching_total_row_is_dropped_and_the_slot_kept(self):
        ed, rows = self._extract("$33.00")
        assert [r["Description"] for r in rows] == ["Pens", "Ink"]
        assert ed["validation"]["duplicate_total_row_count"] == 1
        assert any("repeating a total" in n for n in ed["validation_notes"])
        tot = next(f["ref"] for f in ed["slot_map"]["fields"] if f["row_label"] == "Total")
        assert ed["extracted_fields"][tot] == "$33.00"
        assert not any(str(f.get("reason")).startswith("total_row_mismatch")
                       for f in ed["validation"]["flagged_fields"])

    def test_a_differing_total_row_is_kept_and_both_flagged(self):
        ed, rows = self._extract("$34.00")
        assert [r["Description"] for r in rows] == ["Pens", "Ink", "Total"]
        reasons = [str(f.get("reason")) for f in ed["validation"]["flagged_fields"]]
        assert sum(r.startswith("total_row_mismatch") for r in reasons) == 2, reasons
        tot = next(f["ref"] for f in ed["slot_map"]["fields"] if f["row_label"] == "Total")
        assert ed["validation"]["confidence_map"][tot] == "low"
        assert rows[2]["_confidence"] == "low"
        assert "total_row_mismatch" in ed["field_provenance"][tot]["review_reasons"]
        assert ed["needs_review"] is True


class TestC4InvoiceTotalsBlock:
    """Owner report: the export of flowparse_invoice_tax lost its totals
    block. No model answer for it is recorded anywhere in the repository, so
    the answer below is WRITTEN FROM THE PDF'S OWN TEXT (tests/golden) and
    stands in for the model; the PDF's real text layer is what grounding
    checks it against."""

    @pytest.fixture(scope="class")
    def result(self):
        from core.preprocessor import preprocess_file
        from slot_extractor import enumerate_slots, run_slot_extraction
        from tests.contract.run_a_driver import DOCS, model_response, template_grid
        grid = template_grid("AP_Inv_Full")
        slots = enumerate_slots(grid)
        with contextlib.redirect_stdout(io.StringIO()):
            d = preprocess_file(DOCS / "invoice/flowparse_invoice_tax.pdf")
        want = {"Vendor Name": ("Harwood Design Studio Ltd",
                                "Harwood Design Studio Ltd INVOICE HD-2026-0142"),
                "Invoice Number": ("HD-2026-0142",
                                   "Harwood Design Studio Ltd INVOICE HD-2026-0142"),
                "Subtotal": ("£3,280.00", "Subtotal £3,280.00"),
                "Tax Total": ("£656.00", "VAT 20% £656.00"),
                "Invoice Total": ("£3,936.00", "TOTAL DUE £3,936.00")}
        fields = {f["slot_id"]: {"value": want[f["row_label"]][0],
                                 "source": want[f["row_label"]][1], "page": 1}
                  for f in slots["fields"] if f["row_label"] in want}
        lines = [ln for ln in d.page_texts[0].splitlines() if ln[:2] in
                 ("1 ", "2 ", "3 ", "4 ", "5 ")]
        rows = [{"cells": {"Line": ln.split()[0], "Description": "",
                           "Line Amount": ln.split()[-1]},
                 "source": ln, "page": 1} for ln in lines]
        answer = {"fields": fields, "tables": {"table": rows}}
        llm = SimpleNamespace(extract=lambda **k: model_response(answer))
        with contextlib.redirect_stdout(io.StringIO()):
            res = run_slot_extraction(
                SimpleNamespace(llm=llm), DOCS / "invoice/flowparse_invoice_tax.pdf",
                {"layout": grid}, None, page_images=[], doc_text=d.extracted_text,
                doc_text_pages=d.page_texts, file_type="digital_pdf",
                default_doc_type="invoice", start=0.0, page_lines=d.page_lines,
                page_numbers=[1])[0]
        return grid, slots, res.extracted_data

    def test_the_template_gives_the_totals_block_slots(self, result):
        _grid, slots, _ed = result
        labels = {f["row_label"] for f in slots["fields"]}
        assert {"Subtotal", "Discount", "Shipping or Handling", "Tax Total",
                "Invoice Total"} <= labels
        assert slots["tables"][0]["end_row"] == 33          # was 39: it swallowed them

    def test_the_three_totals_are_in_the_file(self, result):
        grid, _slots, ed = result
        assert len(ed["table_rows"]) == 5
        wb, _ = export([doc(ed, "flowparse_invoice_tax.pdf")], grid,
                       "c4_flowparse_invoice_tax")
        ws = wb["Results"]
        found = {ws.cell(r, 1).value: ws.cell(r, 2).value
                 for r in range(1, ws.max_row + 1)}
        assert found["Subtotal"] == 3280.0
        assert found["Tax Total"] == 656.0
        assert found["Invoice Total"] == 3936.0
        assert ws.cell(next(r for r in range(1, ws.max_row + 1)
                            if ws.cell(r, 1).value == "Subtotal"), 2).number_format \
            == '"£"#,##0.00'
