"""A1/A2 — wrong-slot and duplicate values, and repeated box entries.

Reproductions of the real staging exports job 42 (flowparse_invoice_tax) and
job 51 (pitt_sample_w2): the scripted answers are what the real model returned
(the quotes are copied from the exports' cell comments).
"""

from __future__ import annotations

from tests import overnight_helpers as H

INVOICE = "invoice/flowparse_invoice_tax.pdf"
PITT = "w2/pitt_sample_w2.pdf"

W2_LABELS = [
    "Tax Year", "Box a Employee SSN", "Box b Employer EIN", "Box c Employer Name",
    "Employer Address", "Box d Control Number", "Box e Employee Name",
    "Box f Employee Address", "Box 1 Wages Tips Other Compensation",
    "Box 2 Federal Income Tax Withheld", "Box 3 Social Security Wages",
    "Box 4 Social Security Tax Withheld", "Box 5 Medicare Wages and Tips",
    "Box 6 Medicare Tax Withheld", "Box 7 Social Security Tips",
    "Box 8 Allocated Tips", "Box 10 Dependent Care Benefits",
    "Box 11 Nonqualified Plans", "Box 13 Statutory Employee",
    "Box 13 Retirement Plan", "Box 13 Third-Party Sick Pay", "Box 14 Other",
]
W2_TABLES = [
    ("Box 12 Codes", ["Box 12 Code", "Box 12 Amount"], 4),
    ("State and Local", ["State", "Employer State ID", "State Wages",
                         "State Income Tax", "Local Wages", "Local Income Tax",
                         "Locality Name"], 2),
]
STATE_LINE = ("15 State Employer’sstateIDno.16Statewages,tips,etc. PA XXXX5369 "
              "47808.35 17Stateincometax 18Localwages,tips,etc. 1467.72 47808.35 "
              "19Localincometax 20Localityname 478.08 700102")


def pitt_grid():
    return H.column_grid(W2_LABELS, W2_TABLES)


def pitt_answer(g, *, state_rows=None):
    a = H.ans
    f = {
        "Tax Year": a("2026", "2026 W-2 and EARNINGS SUMMARY"),
        "Box a Employee SSN": a("XXX-XX-1234", "XX-XXX5591 XXX-XX-1234"),
        "Box b Employer EIN": a("XX-XXX5591", "XX-XXX5591 XXX-XX-1234"),
        "Box c Employer Name": a("UNIVERSITY OF PITTSBURGH", "UNIVERSITY OF PITTSBURGH"),
        "Employer Address": a("200 SOUTH CRAIG STREET SUITE 230 PITTSBURGH, PA 15260",
                              "200 SOUTH CRAIG STREET SUITE 230 PITTSBURGH, PA 15260"),
        "Box d Control Number": a("0000005712UUQ", "0000005712UUQ CKR5 16260"),
        "Box e Employee Name": a("ELIZABETH A DARLING", "ELIZABETH A DARLING"),
        "Box f Employee Address": a("2001 CAMPUS DRIVE PITTSBURGH, PA 15237",
                                    "2001 CAMPUS DRIVE PITTSBURGH, PA 15237"),
        "Box 1 Wages Tips Other Compensation": a("44629.35", "44629.35 7631.62"),
        "Box 2 Federal Income Tax Withheld": a("7631.62", "44629.35 7631.62"),
        "Box 3 Social Security Wages": a("48736.35", "48736.35 3021.65"),
        "Box 4 Social Security Tax Withheld": a("3021.65", "48736.35 3021.65"),
        "Box 5 Medicare Wages and Tips": a("48736.35", "48736.35 706.68"),
        "Box 6 Medicare Tax Withheld": a("706.68", "48736.35 706.68"),
        "Box 10 Dependent Care Benefits": a("1000.00", "1000.00"),
        # what the real model returned (job 51): Box 12a's amount, Box 11 is blank
        "Box 11 Nonqualified Plans": a("4107.00", "E 4107.00"),
        # the only X on the page sits under "Ret. plan"
        "Box 13 Statutory Employee": a("X", "X"),
        "Box 13 Retirement Plan": a("X", "13Statemp.Ret.plan3rdpartysickpay X"),
        "Box 14 Other": a("1600.00", "14 Other 1600.00 14H"),
    }
    fields = {H.field_id(g, k): v for k, v in f.items()}
    box12 = H.table_name(g, "Box 12 Codes")
    state = H.table_name(g, "State and Local")
    rows12 = [
        {"cells": {"Box 12 Code": "E", "Box 12 Amount": "4107.00"},
         "source": "E 4107.00 SocialSecurityNumber: XXX-XX-0000", "page": 1},
        {"cells": {"Box 12 Code": "W", "Box 12 Amount": "1500.00"},
         "source": "12b W 1500.00", "page": 1},
        # job 51: Box 14's second entry, answered as a Box 12 row with no code
        {"cells": {"Box 12 Code": "", "Box 12 Amount": "52.00"},
         "source": "12c 52.00", "page": 1},
    ]
    if state_rows is None:
        state_rows = [{"cells": {"State": "PA", "Employer State ID": "XXXX5369",
                                 "State Wages": "47808.35",
                                 "State Income Tax": "1467.72",
                                 "Local Wages": "47808.35",
                                 "Local Income Tax": "478.08",
                                 "Locality Name": "700102"},
                       "source": STATE_LINE, "page": 1}]
    return {"fields": fields, "tables": {box12: rows12, state: state_rows}}


def _rows(data, g, title):
    return data.get(f"{H.table_name(g, title)}_rows") or []


def test_a1b_box11_takes_no_value_from_box12a():
    g = pitt_grid()
    data, _ = H.run(PITT, g, pitt_answer(g), doc_type="w2")
    assert H.value(data, "Box 11 Nonqualified Plans") == ""
    assert "Box 11 Nonqualified Plans" not in H.flagged_refs(data), (
        "Box 11 is blank on the page: plainly empty, never flagged")
    amounts = [r.get("Box 12 Amount") for r in _rows(data, g, "Box 12 Codes")]
    assert "4107.00" in amounts


def test_a1b_box13_checkbox_follows_the_x_position():
    g = pitt_grid()
    data, _ = H.run(PITT, g, pitt_answer(g), doc_type="w2")
    assert H.value(data, "Box 13 Retirement Plan") == "X"
    assert H.value(data, "Box 13 Statutory Employee") == ""
    assert H.value(data, "Box 13 Third-Party Sick Pay") == ""
    assert "Box 13 Statutory Employee" not in H.flagged_refs(data)


def test_a1b_correct_w2_values_are_untouched():
    g = pitt_grid()
    data, _ = H.run(PITT, g, pitt_answer(g), doc_type="w2")
    # Box 3 and Box 5 legitimately share 48736.35 from two different lines
    assert H.value(data, "Box 3 Social Security Wages") == "48736.35"
    assert H.value(data, "Box 5 Medicare Wages and Tips") == "48736.35"
    assert H.value(data, "Box 14 Other") == "1600.00"
    assert H.value(data, "Box 10 Dependent Care Benefits") == "1000.00"


def test_a2_box14_second_entry_is_not_placed_in_box12():
    g = pitt_grid()
    data, _ = H.run(PITT, g, pitt_answer(g), doc_type="w2")
    amounts = [r.get("Box 12 Amount") for r in _rows(data, g, "Box 12 Codes")]
    assert "52.00" not in amounts, amounts
    text = H.flag_text(data)
    assert "box 14 has a second entry 52.00 x that has no slot" in text, text
    prov = (data.get("field_provenance") or {})
    box14_ref = next(f["ref"] for f in H.slots(g)["fields"]
                     if f["row_label"] == "Box 14 Other")
    assert "14H" in str(prov.get(box14_ref, {}).get("entry_codes")
                        or prov.get(box14_ref, {}).get("source")), prov.get(box14_ref)


INV_LABELS = [
    "Vendor Name", "Vendor Address", "Vendor Tax or VAT ID", "Invoice Number",
    "Invoice Date", "Due Date", "Purchase Order Number", "Payment Terms",
    "Currency", "Bill To Name", "Bill To Address", "Ship To Address",
    "Remit To Bank", "Remit To Account Number", "Payment Instructions",
]
PAY_LINE = ("Payment within 30 days to Harwood Design Studio Ltd · Sort code "
            "20-45-77 · Account 83319204")


def test_a1a_remit_to_bank_does_not_take_the_vendor_name():
    g = H.column_grid(INV_LABELS)
    a = H.ans
    f = {
        "Vendor Name": a("Harwood Design Studio Ltd", "Harwood Design Studio Ltd"),
        "Invoice Number": a("HD-2026-0142", "INVOICE HD-2026-0142"),
        "Payment Terms": a("Payment within 30 days", PAY_LINE),
        "Bill To Name": a("Bright Harbour Ltd", "Bright Harbour Ltd"),
        "Remit To Bank": a("Harwood Design Studio Ltd", PAY_LINE),
        "Remit To Account Number": a("83319204", PAY_LINE),
        "Payment Instructions": a(PAY_LINE, PAY_LINE),
    }
    answer = {"fields": {H.field_id(g, k): v for k, v in f.items()}, "tables": {}}
    data, _ = H.run(INVOICE, g, answer, doc_type="invoice")
    assert H.value(data, "Remit To Bank") == ""
    assert "Remit To Bank" not in H.flagged_refs(data)
    assert H.value(data, "Vendor Name") == "Harwood Design Studio Ltd"
    assert H.value(data, "Remit To Account Number") == "83319204"
    assert H.value(data, "Payment Instructions") == PAY_LINE
