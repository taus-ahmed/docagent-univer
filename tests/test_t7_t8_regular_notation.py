"""Run T, 7 and 8 in the Regular export (the slot writer).

7  A trailing minus stays trailing: "26.08-" is a NEGATIVE number cell whose
   format draws it "26.08-" (`#,##0.00;#,##0.00-`), so sums still work.
   Leading minus and parentheses keep their own notation.
8  Identifiers keep every printed character: "0025" stays "0025"; a column
   mixing plain and zero-padded digit runs is text throughout; "P.O." is an
   identifier heading. Money keeps its printed decimals.

The Excel check at the end opens the written file in Excel itself (COM, via
PowerShell) and reads each cell's DISPLAYED text; it is skipped where Excel
is not installed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from template_shape import compute_shape  # noqa: E402
from app.services.excel_cells import (cell_format, coerce_cell_value,  # noqa: E402
                                      column_keeps_text, labels_an_identifier,
                                      trailing_minus)


@pytest.mark.parametrize("printed,value,fmt", [
    ("26.08-", -26.08, "#,##0.00;#,##0.00-"),
    ("$1,204.00-", -1204.0, '"$"#,##0.00;"$"#,##0.00-'),
    ("1,204.00 -", -1204.0, "#,##0.00;#,##0.00-"),
    ("-26.08", -26.08, "#,##0.00"),
    ("(26.08)", -26.08, "#,##0.00_);(#,##0.00)"),
    ("€26,08-", None, None),          # a decimal comma: whatever it is, never "-26.08"-formatted
])
def test_sign_conventions(printed, value, fmt):
    v = coerce_cell_value(printed, "Amount", "." if "€" not in printed else ",")
    if value is None:
        assert cell_format(printed, "Amount", ",") in (None, "#,##0.00;#,##0.00-",
                                                       '"€"#,##0.00;"€"#,##0.00-')
        return
    assert v == value and cell_format(printed, "Amount") == fmt


def test_trailing_minus_shape():
    assert trailing_minus("26.08-") and trailing_minus("$1,204.00 -")
    assert not trailing_minus("-26.08")
    assert not trailing_minus("ACCT-") and not trailing_minus("12-34-56")


@pytest.mark.parametrize("label", ["P.O.", "PO", "Invoice #", "Check No", "ZIP"])
def test_identifier_headings(label):
    assert labels_an_identifier(label)
    assert coerce_cell_value("26007893", label) == "26007893"


def test_quantities_stay_numbers():
    assert coerce_cell_value("40", "Qty") == 40.0
    assert coerce_cell_value("75.00", "Net") == 75.0 and cell_format("75.00", "Net") == "#,##0.00"


def test_column_rule():
    assert column_keeps_text(["0025", "2937", "629239"])
    assert not column_keeps_text(["25", "2937"])
    assert not column_keeps_text(["0", "12"])               # a lone zero is zero


def _grid():
    return {"cells": {"0,0": {"value": "Ref"}, "0,1": {"value": "Description"},
                      "0,2": {"value": "Amount"}},
            "colWidths": [], "repeatRows": [], "merges": {},
            "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 6, "c2": 2,
                         "orientation": "rows", "name": "T"}]}


def _write(tmp_path, rows):
    import openpyxl
    from openpyxl import Workbook
    from app.api.routes.extract import _write_slot_excel
    from slot_extractor import run_slot_extraction
    lines = ["Ref Description Amount"] + [f"{r['Ref']} {r['Description']} {r['Amount']}"
                                          for r in rows]
    text = "\n".join(lines) + "\n"
    payload = {"fields": {}, "tables": {"T": [dict(cells=r, source=ln, page=1, **r)
                                               for r, ln in zip(rows, lines[1:])]}}

    class _Resp:
        success = True
        parsed_json = payload
        raw_text = json.dumps(payload)

    class _LLM:
        def extract(self, **kw):
            return _Resp()
    grid = _grid()
    shape = compute_shape(grid, log=lambda _m: None)
    ed = run_slot_extraction(type("O", (), {"llm": _LLM()})(), "S.pdf",
                             {"layout": grid, "shape": shape}, None, page_images=[],
                             doc_text=text, doc_text_pages=[text], file_type="digital_pdf",
                             default_doc_type="other", start=0.0)[0].extracted_data

    class _Doc:
        filename = "S.pdf"

        def get_extracted_data(self):
            return ed
    wb = Workbook()
    _write_slot_excel(wb.active, [_Doc()], grid, grid["cells"], openpyxl)
    out = tmp_path / "t.xlsx"
    wb.save(out)
    return wb.active, out


ROWS = [{"Ref": "0025", "Description": "Monthly fee", "Amount": "26.08-"},
        {"Ref": "2937", "Description": "Service", "Amount": "75.00"},
        {"Ref": "013179", "Description": "Refund", "Amount": "(12.50)"},
        {"Ref": "12523", "Description": "Adjustment", "Amount": "-3.10"}]


def _cells(ws):
    out = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value is not None:
                out[str(c.value)] = c
    return out


def test_the_written_sheet(tmp_path):
    ws, _ = _write(tmp_path, ROWS)
    cells = _cells(ws)
    for ref in ("0025", "2937", "013179", "12523"):
        assert ref in cells and cells[ref].value == ref       # text, every character
    neg = cells["-26.08"]
    assert neg.value == -26.08 and neg.number_format == "#,##0.00;#,##0.00-"
    assert cells["75.0"].number_format == "#,##0.00"
    assert cells["-12.5"].number_format == "#,##0.00_);(#,##0.00)"
    assert cells["-3.1"].number_format == "#,##0.00"


def _excel_texts(path, coords):
    ps = shutil.which("powershell") or shutil.which("powershell.exe")
    if not ps:
        return None
    script = (
        "$ErrorActionPreference='Stop';"
        "try { $x = New-Object -ComObject Excel.Application } catch { exit 3 };"
        "$x.DisplayAlerts=$false;"
        f"$w=$x.Workbooks.Open('{path}');$s=$w.Worksheets.Item(1);"
        + "".join(f"Write-Output ($s.Range('{c}').Text);" for c in coords)
        + "$w.Close($false);$x.Quit()")
    r = subprocess.run([ps, "-NoProfile", "-Command", script], capture_output=True,
                       timeout=120)
    if r.returncode == 3:
        return None
    return r.stdout.decode("utf-8", "replace").splitlines()


def test_excel_displays_the_trailing_minus(tmp_path):
    ws, path = _write(tmp_path, ROWS)
    cells = _cells(ws)
    coords = [cells[k].coordinate for k in ("-26.08", "-12.5", "-3.1", "0025", "75.0")]
    got = _excel_texts(str(path.resolve()), coords)
    if got is None:
        pytest.skip("Excel is not installed here")
    assert [g.strip() for g in got] == ["26.08-", "(12.50)", "-3.10", "0025", "75.00"]
