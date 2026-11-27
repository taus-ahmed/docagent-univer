"""Run T, owner priority — no-template headers are the page's own labels.

Inference named a column printed `INVOICE` "Invoice Number" and wrote
"Description" over a column of row labels the page leaves unheaded. Now: a
column whose heading the page prints over its values is called exactly that;
one with no printed heading keeps a neutral name MARKED inferred; a field
label the page does not print is replaced by the `Label:` printed before its
value, else marked inferred. Applied to the result only: the prompt is the
same, so cached answers stay valid. Two vocabularies; negatives.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from tests import run_q_support as Q
from tests.harness import bootstrap as bs

bs.bootstrap()

CASES = {
    "en": {"title": "Vendor Invoice List", "heads": ["INVOICE", "INV DATE", "NET"],
           "model": ["Invoice Number", "Invoice Date", "Net Amount"],
           "rows": [("0025", "06/22/2026", "75.00"), ("2937", "06/16/2026", "2,480.00")],
           "field": ("Customer ID", "Acct No:", "4471-22")},
    "es": {"title": "Lista de facturas", "heads": ["FACTURA", "FECHA", "IMPORTE"],
           "model": ["Numero de factura", "Fecha de factura", "Importe neto"],
           "rows": [("A-77", "02/21/2024", "10.00"), ("A-78", "02/22/2024", "20.00")],
           "field": ("Client Code", "Cliente:", "KX-77")},
}


def _run(tmp_path, case, extra_cols=()):
    import extractor
    c = CASES[case]
    xs = [140, 260, 420]
    lab, plabel, pval = c["field"]
    items = [(40, 770, c["title"]), (40, 752, plabel), (110, 752, pval)]
    items += [(x, 730, h) for x, h in zip(xs, c["heads"])]
    labels = ["Freight", "Supplies"]
    for i, r in enumerate(c["rows"]):
        items.append((40, 714 - 14 * i, labels[i]))
        items += [(x, 714 - 14 * i, v) for x, v in zip(xs, r)]
    pdf = Q.make_pdf(tmp_path / "n.pdf", [items], size=9)
    cols = ["Description"] + c["model"]
    inferred = {"document_type": "invoice", "title": c["title"],
                "fields": [lab, "Company Name"], "totals": [],
                "tables": [{"name": "Invoices", "row_count": 2, "columns": cols}]}
    rows = [dict(zip(cols, (labels[i],) + r), source=f"{labels[i]} {' '.join(r)}", page=1)
            for i, r in enumerate(c["rows"])]
    answer = {"fields": {"F1": {"value": pval, "source": f"{plabel} {pval}", "page": 1,
                                "status": "found"},
                         "F2": {"value": c["title"], "source": c["title"], "page": 1,
                                "status": "found"}},
              "tables": {"Invoices": rows}}
    calls = []

    def extract(prompt="", system_instruction="", **kw):
        calls.append(prompt)
        if (system_instruction or "").startswith("You are a document analyst"):
            return Q._Resp(copy.deepcopy(inferred))
        return Q._Resp(copy.deepcopy(answer))
    ed = extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                  pdf, None)[0].extracted_data
    return ed


@pytest.mark.parametrize("case", ["en", "es"])
def test_columns_take_the_printed_headings(tmp_path, case):
    ed = _run(tmp_path, case)
    c = CASES[case]
    rows = ed["Invoices_rows"]
    for h, (inv, _d, net) in zip([c["heads"][0], c["heads"][2]], [c["rows"][0]] * 2):
        assert h in rows[0], (h, list(rows[0]))
    assert rows[0][c["heads"][0]] == c["rows"][0][0]
    assert not any(m in rows[0] for m in c["model"])
    heads = [col["header"] for t in ed["slot_map"]["tables"] for col in t["columns"]]
    assert all(h in heads for h in c["heads"])
    grid_text = {str(v.get("value")) for v in ed["inferred_grid"]["cells"].values()}
    assert all(h in grid_text for h in c["heads"])


@pytest.mark.parametrize("case", ["en", "es"])
def test_an_unheaded_column_is_marked_inferred(tmp_path, case):
    ed = _run(tmp_path, case)
    assert "Description" in (ed.get("inferred_headers") or {}).get("Invoices", {})


@pytest.mark.parametrize("case", ["en", "es"])
def test_a_field_takes_the_label_printed_before_its_value(tmp_path, case):
    ed = _run(tmp_path, case)
    lab, plabel, pval = CASES[case]["field"]
    want = plabel.rstrip(":")
    assert want in ed["extracted_data"] and lab not in ed["extracted_data"]
    assert ed["extracted_data"][want]["value"] == pval


def test_a_field_with_no_printed_label_is_marked_inferred(tmp_path):
    ed = _run(tmp_path, "en")
    assert "Company Name" in (ed.get("inferred_headers") or {}).get("_fields", {})


def test_the_writer_marks_an_inferred_label(tmp_path):
    import openpyxl
    from openpyxl import Workbook
    from app.services.excel_slot import _write_inferred_sheets
    ed = _run(tmp_path, "en")

    class _Doc:
        filename = "n.pdf"
        id = 1

        def get_extracted_data(self):
            return ed
    wb = Workbook()
    _write_inferred_sheets(wb, wb.active, [_Doc()], openpyxl)
    cells = [c for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value]
    hit = [c for c in cells if c.value == "Company Name"]
    assert hit and hit[0].comment and "LABEL INFERRED" in hit[0].comment.text
    inv = [c for c in cells if c.value == "INVOICE"]
    assert inv and not inv[0].comment
