"""Run S, Stage 1b — a group header's identifier and name are two columns on
every row of its group.

A grouped list prints a group line (an identifier and a name) above the
group's rows and often a subtotal below them. Job 138 (mobile_vendor_list,
a live run after Run R) kept 0 of 31 vendor numbers: the model answered the
group column with the NAME only, and `row_groups.apply` filled the column
only when it was empty, so the page's own `300055` never reached the sheet.

The rules, in several vocabularies and layouts (1d):

  * the identifier and the name come from the PAGE's group line, always;
    a model value that is a part of the line is replaced by the page's,
    a model value that is not is flagged, never silently dropped;
  * the columns are named by the page's own label (`Customer Code:`),
    else a neutral name from context (`Vendor ID` from the title), and an
    engine-chosen NAME is recorded as inferred (amber on the header only).
"""
from __future__ import annotations

import pytest

import row_groups as RG
from tests import run_q_support as Q


def _line(text, page=1, y=0):
    out, x = [], 10.0
    for t in text.split():
        out.append({"text": t, "x0": x, "x1": x + 6 * len(t), "top": y,
                    "bottom": y + 8, "page": page})
        x += 6 * len(t) + 4
    return out


def _lines(texts, page=1):
    return [_line(t, page, 12 * i) for i, t in enumerate(texts)]


# ── splitting a group line ──────────────────────────────────────────────────

@pytest.mark.parametrize("text,label,ident,name", [
    ("300055 ANDERSON DULANEY", None, "300055", "ANDERSON DULANEY"),
    ("C-1001 ACME TRADING CO", None, "C-1001", "ACME TRADING CO"),
    ("EMP0042 Jane Q. Doe", None, "EMP0042", "Jane Q. Doe"),
    ("Customer Code: KX-77 Harbor Foods", "Customer Code", "KX-77", "Harbor Foods"),
    ("Employee ID: 4410 Name: Ravi Patel", "Employee ID", "4410", "Ravi Patel"),
    ("Account 4411-2290 RIVERSIDE HOLDINGS", "Account", "4411-2290", "RIVERSIDE HOLDINGS"),
    ("NORTHWIND SUPPLY", None, None, "NORTHWIND SUPPLY"),
])
def test_split_group_line(text, label, ident, name):
    s = RG.split_group_label(text)
    assert (s["label"], s["ident"], s["name"]) == (label, ident, name)


# ── column names ────────────────────────────────────────────────────────────

def _grouped(head_lines, groups, total=None, page=1):
    """A grouped list: each group = (group line, [row lines], subtotal|None)."""
    body = list(head_lines)
    for g, rows, sub in groups:
        body.append(g)
        body.extend(rows)
        if sub:
            body.append(sub)
    if total:
        body.append(total)
    return _lines(body, page)


VENDOR_PAGE = _grouped(
    ["City Utility Board", "VENDOR INVOICE LIST", "INVOICE INV DATE CHECK # NET PAID STS"],
    [("300055 ANDERSON DULANEY", ["0025 06/22/2026 20218284 75.00 75.00 PD"], None),
     ("299694 B&B LAWN/LANDSCAPING", ["2937 06/16/2026 917846 2,480.00 2,480.00 PD",
                                      "2938 06/17/2026 917846 2,400.00 2,400.00 PD"], "4,880.00"),
     ("20320 BAGBY ELECTRIC", ["012523 05/28/2026 917847 100.00 100.00 PD",
                               "013179 05/28/2026 917847 50.00 50.00 PD"], "150.00")],
    "5 INVOICES 5,105.00")

CUSTOMER_PAGE = _grouped(
    ["Receivables ageing", "Ref Date Current Over30 Status"],
    [("Customer Code: KX-77 Harbor Foods", ["A1 03/01/2025 120.00 0.00 open",
                                            "A2 03/04/2025 80.00 10.00 open"], "200.00 10.00"),
     ("Customer Code: KX-81 Delta Bakery", ["B7 03/02/2025 55.50 0.00 open",
                                            "B9 03/09/2025 44.50 5.00 open"], "100.00 5.00")])

EMPLOYEE_PAGE = _grouped(
    ["Employee payroll register", "Code Hours Rate Gross Net"],
    [("EMP0042 Jane Q. Doe", ["REG 40 25.00 1,000.00 800.00",
                              "OT 2 37.50 75.00 60.00"], "1,075.00"),
     ("EMP0057 Ravi Patel", ["REG 38 30.00 1,140.00 912.00",
                             "OT 1 45.00 45.00 36.00"], "1,185.00")])

NO_ID_PAGE = _grouped(
    ["Statement of charges", "Item Date Qty Amount Note"],
    [("NORTHWIND SUPPLY", ["X1 01/02/2025 1 10.00 ok", "X2 01/03/2025 2 20.00 ok"], "30.00"),
     ("SOUTHGATE TOOLS", ["Y1 01/04/2025 1 5.00 ok", "Y2 01/05/2025 3 15.00 ok"], "20.00")])


def test_columns_from_context_when_the_page_prints_no_label():
    g = RG.detect(VENDOR_PAGE)
    cols = RG.group_columns(g, VENDOR_PAGE)
    assert cols["ident"] == {"name": "Vendor ID", "inferred": True}
    assert cols["name"] == {"name": "Vendor Name", "inferred": True}


def test_columns_from_the_pages_own_label():
    g = RG.detect(CUSTOMER_PAGE)
    assert g is not None and len(g.groups) == 2
    cols = RG.group_columns(g, CUSTOMER_PAGE)
    # the identifier's column is the printed label, as printed, colon stripped
    assert cols["ident"] == {"name": "Customer Code", "inferred": False}
    # the page prints no label for the name: neutral, from the label, inferred
    assert cols["name"] == {"name": "Customer Name", "inferred": True}


def test_alphanumeric_employee_ids_with_no_label():
    g = RG.detect(EMPLOYEE_PAGE)
    assert g is not None
    cols = RG.group_columns(g, EMPLOYEE_PAGE)
    assert cols["ident"]["name"] == "Employee ID" and cols["ident"]["inferred"]
    assert cols["name"]["name"] == "Employee Name"


def test_a_group_with_no_identifier_gets_one_name_column():
    g = RG.detect(NO_ID_PAGE)
    assert g is not None
    cols = RG.group_columns(g, NO_ID_PAGE)
    assert cols["ident"] is None
    assert cols["name"]["name"] == "Group" and cols["name"]["inferred"]


def test_the_inferred_table_gets_both_columns_first():
    inf = {"tables": [{"name": "Invoice List", "columns": ["INVOICE", "NET"]}]}
    got = RG.add_group_column(inf, [VENDOR_PAGE])
    assert got == ["Vendor ID", "Vendor Name"]
    assert inf["tables"][0]["columns"] == ["Vendor ID", "Vendor Name", "INVOICE", "NET"]
    assert inf["tables"][0]["inferred_columns"] == ["Vendor ID", "Vendor Name"]


# ── filling ────────────────────────────────────────────────────────────────

def _rows_of(lines, keys, model_group=None):
    rows, where = [], {}
    for i, ln in enumerate(lines):
        if RG._kind(ln) == "row":
            toks = [w["text"] for w in ln]
            r = {k: "" for k in keys}
            r["Ref"] = toks[0]
            r["Amount"] = next(t for t in toks if RG.amount(t) is not None)
            if model_group:
                r.update(model_group(r))
            rows.append(r)
            where[id(r)] = i
    return rows, where


def test_every_row_carries_both_parts_even_when_the_model_gave_the_name_only():
    g = RG.detect(VENDOR_PAGE)
    names = {"0025": "ANDERSON DULANEY", "2937": "B&B LAWN/LANDSCAPING",
             "2938": "", "012523": "BAGBY ELECTRIC", "013179": "BAGBY ELECTRIC"}
    keys = ["Vendor ID", "Vendor Name", "Ref", "Amount"]
    rows, where = _rows_of(VENDOR_PAGE, keys,
                           lambda r: {"Vendor Name": names[r["Ref"]]})
    subs, flags, _n = RG.apply(rows, where, g, None, keys, "grounded", "low",
                               split_keys=("Vendor ID", "Vendor Name"))
    assert [(r["Vendor ID"], r["Vendor Name"]) for r in rows] == [
        ("300055", "ANDERSON DULANEY"), ("299694", "B&B LAWN/LANDSCAPING"),
        ("299694", "B&B LAWN/LANDSCAPING"), ("20320", "BAGBY ELECTRIC"),
        ("20320", "BAGBY ELECTRIC")]
    assert not flags
    assert [(s["Vendor ID"], s["Vendor Name"], s["Amount"]) for s in subs] == [
        ("299694", "B&B LAWN/LANDSCAPING", "4,880.00"),
        ("20320", "BAGBY ELECTRIC", "150.00")]


def test_a_single_group_column_keeps_the_whole_line_and_replaces_a_part():
    """A template with one `Vendor` column: the page's whole group line goes
    in, so the number is not lost when the model answered the name."""
    g = RG.detect(VENDOR_PAGE)
    keys = ["Vendor", "Ref", "Amount"]
    rows, where = _rows_of(VENDOR_PAGE, keys, lambda r: {"Vendor": "ANDERSON DULANEY"}
                           if r["Ref"] == "0025" else {})
    RG.apply(rows, where, g, "Vendor", keys, "grounded", "low")
    assert rows[0]["Vendor"] == "300055 ANDERSON DULANEY"


def test_a_model_value_the_group_line_does_not_print_is_flagged_not_dropped():
    g = RG.detect(VENDOR_PAGE)
    keys = ["Vendor ID", "Vendor Name", "Ref", "Amount"]
    rows, where = _rows_of(VENDOR_PAGE, keys, lambda r: {"Vendor Name": "ZETA CORP"}
                           if r["Ref"] == "0025" else {})
    _s, flags, _n = RG.apply(rows, where, g, None, keys, "grounded", "low",
                             split_keys=("Vendor ID", "Vendor Name"))
    assert rows[0]["Vendor Name"] == "ANDERSON DULANEY"
    assert any("ZETA CORP" in f[2] and "ANDERSON DULANEY" in f[2] for f in flags)


def test_printed_label_groups_fill_the_customer_code():
    g = RG.detect(CUSTOMER_PAGE)
    keys = ["Customer Code", "Customer Name", "Ref", "Amount"]
    rows, where = _rows_of(CUSTOMER_PAGE, keys)
    RG.apply(rows, where, g, None, keys, "grounded", "low",
             split_keys=("Customer Code", "Customer Name"))
    assert [(r["Customer Code"], r["Customer Name"]) for r in rows] == [
        ("KX-77", "Harbor Foods")] * 2 + [("KX-81", "Delta Bakery")] * 2


# ── end to end, on generated PDFs (1d) ─────────────────────────────────────

def _pdf_items(texts):
    return [(56, 760 - 16 * i, t) for i, t in enumerate(texts)]


def _vendor_pdf(path):
    texts = ["City Utility Board", "VENDOR INVOICE LIST",
             "INVOICE INV DATE CHECK # NET PAID STS",
             "300055 ANDERSON DULANEY",
             "0025 06/22/2026 20218284 75.00 75.00 PD",
             "299694 B&B LAWN/LANDSCAPING",
             "2937 06/16/2026 917846 2,480.00 2,480.00 PD",
             "2938 06/17/2026 917846 2,400.00 2,400.00 PD",
             "4,880.00",
             "20320 BAGBY ELECTRIC",
             "012523 05/28/2026 917847 100.00 100.00 PD",
             "013179 05/28/2026 917847 50.00 50.00 PD",
             "150.00",
             "5 INVOICES 5,105.00"]
    return Q.make_pdf(path, [_pdf_items(texts)], size=9), texts


def test_end_to_end_no_template_vendor_numbers_reach_every_row(tmp_path):
    pdf, texts = _vendor_pdf(tmp_path / "vendors.pdf")
    rows_src = [t for t in texts if t[:1].isdigit() and len(t.split()) >= 5]
    inferred = {"document_type": "invoice", "title": "Vendor invoice list",
                "fields": [], "totals": [],
                "tables": [{"name": "Invoices", "row_count": 5,
                            "columns": ["INVOICE", "INV DATE", "NET"]}]}
    by_inv = {"0025": "ANDERSON DULANEY", "2937": "B&B LAWN/LANDSCAPING",
              "2938": "B&B LAWN/LANDSCAPING", "012523": "BAGBY ELECTRIC",
              "013179": "BAGBY ELECTRIC"}

    def answer(prompt):
        rows = []
        for t in rows_src:
            k = t.split()
            # the model answers the group column with the NAME only (job 138)
            rows.append({"Vendor Name": by_inv[k[0]], "INVOICE": k[0],
                         "INV DATE": k[1], "NET": k[3], "source": t, "page": 1})
        return {"fields": {}, "tables": {"Invoices": rows}}

    import copy
    from tests.harness import bootstrap as bs
    bs.bootstrap()
    import extractor
    from types import SimpleNamespace
    calls = []

    def extract(prompt="", system_instruction="", **kw):
        calls.append(prompt)
        if (system_instruction or "").startswith("You are a document analyst"):
            return Q._Resp(copy.deepcopy(inferred))
        if len(calls) <= 2:
            return Q._Resp(answer(prompt))
        r = Q._Resp(None, "")
        r.error = "scripted: no further answer"
        return r

    res = extractor.run_extraction(SimpleNamespace(llm=SimpleNamespace(extract=extract)),
                                   pdf, None)
    ed = res[0].extracted_data
    rows = ed["Invoices_rows"]
    assert len(rows) == 5
    assert [r["Vendor ID"] for r in rows] == ["300055", "299694", "299694", "20320", "20320"]
    assert all(r["Vendor Name"] for r in rows)
    assert ed["inferred_headers"]["Invoices"] == {
        "Vendor ID": RG.INFERRED_NAME, "Vendor Name": RG.INFERRED_NAME}


def test_the_export_marks_an_inferred_header_amber_and_only_the_header(tmp_path):
    import json
    import openpyxl
    from app.models.models import DocumentResult
    from app.services.excel_slot import _write_inferred_sheets
    pdf, _t = _vendor_pdf(tmp_path / "v.pdf")
    # a minimal stored result carrying an inferred header
    from shape_inference import build_grid
    inf = {"document_type": "invoice", "title": "T", "fields": [], "totals": [],
           "tables": [{"name": "Invoices", "row_count": 2,
                       "columns": ["Vendor ID", "Vendor Name", "NET"]}]}
    grid = build_grid(inf)
    from template_shape import compute_shape
    shape = compute_shape(grid)
    band = shape["repeat_bands"][0]
    ed = {"template_type": "slot", "inferred_template": inf, "inferred_grid": grid,
          "shape_signature": "s1",
          "slot_map": {"fields": [], "tables": [{
              "name": "Invoices", "header_row": band["header_row"],
              "start_row": band["start_row"], "end_row": band["end_row"],
              "columns": [{"header": c["header"], "key": c.get("key") or c["header"],
                           "col": c["col"]} for c in band["columns"]]}]},
          "Invoices_rows": [{"Vendor ID": "300055", "Vendor Name": "ANDERSON DULANEY",
                             "NET": "75.00", "_confidence": "grounded"}],
          "inferred_headers": {"Invoices": {"Vendor ID": RG.INFERRED_NAME,
                                            "Vendor Name": RG.INFERRED_NAME}},
          "validation": {}}
    d = DocumentResult(id=1, job_id=1, filename="v.pdf", original_filename="v.pdf",
                       extraction_json=json.dumps(ed), needs_review=False, reviewed=False)
    wb = openpyxl.Workbook()
    _write_inferred_sheets(wb, wb.active, [d], openpyxl)
    ws = wb.worksheets[0]
    cells = {c.value: c for row in ws.iter_rows() for c in row if c.value is not None}
    head = cells["Vendor ID"]
    assert head.fill.fgColor.rgb == "FFFFEB9C"
    assert "page prints no label" in head.comment.text
    assert cells["NET"].fill.fgColor.rgb in (None, "00000000")
    value = cells.get(300055) or cells.get("300055")
    assert value is not None and value.fill.fgColor.rgb in (None, "00000000")
