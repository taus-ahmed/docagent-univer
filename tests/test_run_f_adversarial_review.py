"""Offline adversarial review of the Run E/F text-cue rules.

Every extraction below uses a scripted model answer and synthetic document
geometry.  There are no provider clients, live model calls, or remote files.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

import tests.test_batch2_failure_classes as B


def _run(lines, grid, *, fields=(), tables=None, doc_type="other"):
    """Run a realistic one-page document and a scripted answer through the
    production post-model seam.

    ``fields`` entries are ``(label, occurrence, value, exact source line)``.
    """
    import llm_contract as C
    from slot_extractor import run_slot_extraction
    from text_layer import text_from_lines

    page_lines = [B.D.words(1, lines)]
    page_texts = [text_from_lines(page_lines[0])]
    answer_fields = {}
    for label, occurrence, value, source in fields:
        answer_fields[B._field_id(grid, label, occurrence)] = {
            "value": value,
            "source": source,
            "page": 1,
        }
    answer = B._answer(fields=answer_fields, tables=tables or {})

    def extract(**_kwargs):
        return B.D.model_response(copy.deepcopy(answer))

    with C.collect_attempts(fresh=True):
        result = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)),
            "offline-adversarial-fixture.pdf",
            {"layout": grid},
            None,
            page_images=[],
            doc_text=page_texts[0],
            doc_text_pages=page_texts,
            file_type="digital_pdf",
            default_doc_type=doc_type,
            start=0.0,
            page_lines=page_lines,
            page_origins={1: "native"},
            page_numbers=[1],
            unreadable=None,
        )[0]
    return result.extracted_data


def _field_value(data, label):
    entry = (data.get("extracted_data") or {}).get(label)
    return entry.get("value", "") if isinstance(entry, dict) else entry or ""


def _no_data_message(data):
    return any("no data found" in str(item.get("text") or "").casefold()
               for item in data.get("attention") or [])


def _table_grid(headers, *, name="Rows", start=0):
    cells = {f"{start},{column}": header
             for column, header in enumerate(headers)}
    return B._grid(
        cells,
        regions=[{
            "type": "table",
            "name": name,
            "orientation": "rows",
            "r1": start,
            "c1": 0,
            "r2": start + 4,
            "c2": len(headers) - 1,
        }],
    )


def _table_answer(grid, rows, sources):
    table = B._slots(grid)["tables"][0]
    answer = [{"cells": row, "source": source, "page": 1}
              for row, source in zip(rows, sources)]
    return table, {table["name"]: answer}


def _rows(data, table):
    return data[f"{table['name']}_rows"]


# ---------------------------------------------------------------------------
# F1: labels and leader lines must not erase grounded values.


def test_f1_a_mostly_blank_real_form_keeps_its_few_answered_values():
    lines = [
        "EMPLOYEE BENEFIT ENROLLMENT",
        "Employee: Alex Rivera",
        "Effective Date: 1 November 2026",
        "Plan: ____________",
        "Dependent 1: ____________",
        "Dependent 2: ____________",
        "Dental option: ____________",
        "Vision option: ____________",
        "Beneficiary: ____________",
        "Signature: ____________",
        "HR approval: ____________",
    ]
    grid = B._scalar_grid("Employee", "Effective Date")
    data = _run(
        lines,
        grid,
        doc_type="form",
        fields=[
            ("Employee", 0, "Alex Rivera", lines[1]),
            ("Effective Date", 0, "1 November 2026", lines[2]),
        ],
    )

    assert _field_value(data, "Employee") == "Alex Rivera"
    assert _field_value(data, "Effective Date") == "1 November 2026"
    assert not _no_data_message(data)


def test_f1_invoice_leader_lines_do_not_make_real_invoice_values_blank():
    lines = [
        "NORTH STAR ELECTRICAL LTD — INVOICE",
        "Invoice number: NS-10482",
        "Amount due: $2,418.60",
        "Customer reference: ____________________",
        "Delivery notes: ____________________",
        "Project code: ____________________",
        "Site contact: ____________________",
        "Authorised by: ____________________",
        "Remittance advice: ____________________",
        "Internal use: ____________________",
    ]
    grid = B._scalar_grid("Invoice Number", "Amount Due")
    data = _run(
        lines,
        grid,
        doc_type="invoice",
        fields=[
            ("Invoice Number", 0, "NS-10482", lines[1]),
            ("Amount Due", 0, "$2,418.60", lines[2]),
        ],
    )

    assert _field_value(data, "Invoice Number") == "NS-10482"
    assert _field_value(data, "Amount Due") == "$2,418.60"
    assert not _no_data_message(data)


# ---------------------------------------------------------------------------
# F2: legitimate payslip values can be prose or lead a numbered-looking line.


@pytest.mark.parametrize(
    "label,value,line",
    [
        (
            "Net Pay",
            "$1,842.73",
            "Your net pay for this period is $1,842.73 and it will be deposited to your account today.",
        ),
        (
            "Hours",
            "38.5",
            "For this pay period, you worked 38.5 hours and were on site for all five scheduled days.",
        ),
    ],
    ids=["net-pay-in-sentence", "hours-in-sentence"],
)
def test_f2_real_payslip_figure_in_a_sentence_is_data(label, value, line):
    grid = B._scalar_grid(label)
    data = _run(["PAY ADVICE", line], grid, doc_type="payslip",
                fields=[(label, 0, value, line)])

    assert _field_value(data, label) == value
    assert not _no_data_message(data)


def test_f2_leading_eight_on_an_overtime_line_can_be_real_hours():
    line = "8. Overtime 12.50"
    grid = B._scalar_grid("Hours")
    data = _run(["PAY ADVICE", line], grid, doc_type="payslip",
                fields=[("Hours", 0, "8", line)])

    assert _field_value(data, "Hours") == "8"
    assert not _no_data_message(data)


# ---------------------------------------------------------------------------
# F3: SAMPLE can be a real name or a single watermark.


def test_f3_sample_in_real_vendor_and_person_names_is_not_a_placeholder():
    lines = [
        "COMMERCIAL INVOICE",
        "Vendor: Sample Industries Ltd",
        "Contact: Morgan Sample",
        "Invoice number: SI-7781",
    ]
    grid = B._scalar_grid("Vendor", "Contact")
    data = _run(
        lines,
        grid,
        doc_type="invoice",
        fields=[
            ("Vendor", 0, "Sample Industries Ltd", lines[1]),
            ("Contact", 0, "Morgan Sample", lines[2]),
        ],
    )

    assert _field_value(data, "Vendor") == "Sample Industries Ltd"
    assert _field_value(data, "Contact") == "Morgan Sample"


def test_f3_one_sample_watermark_does_not_clear_real_page_data():
    lines = [
        "SAMPLE",
        "TAX INVOICE",
        "Vendor: Mesa Fabrication LLC",
        "Invoice number: MF-2046",
        "Total due: $786.40",
    ]
    grid = B._scalar_grid("Vendor", "Invoice Number", "Total Due")
    data = _run(
        lines,
        grid,
        doc_type="invoice",
        fields=[
            ("Vendor", 0, "Mesa Fabrication LLC", lines[2]),
            ("Invoice Number", 0, "MF-2046", lines[3]),
            ("Total Due", 0, "$786.40", lines[4]),
        ],
    )

    assert [_field_value(data, label)
            for label in ("Vendor", "Invoice Number", "Total Due")] == [
        "Mesa Fabrication LLC", "MF-2046", "$786.40",
    ]


# ---------------------------------------------------------------------------
# F4: a short value immediately before its own label is not always a callout.


@pytest.mark.parametrize(
    "label,value,line",
    [
        ("Qty", "5", "5 Qty  Stainless bolts"),
        ("Hours", "12", "12 Hours  Site labour"),
        ("Units", "3", "3 Units  Replacement pumps"),
        ("Total items", "2", "2 Total items  Packed for dispatch"),
    ],
    ids=["5-qty", "12-hours", "3-units", "2-total-items"],
)
def test_f4_value_before_its_label_is_real_data(label, value, line):
    grid = B._scalar_grid(label)
    data = _run(["WORK ORDER", line], grid, doc_type="invoice",
                fields=[(label, 0, value, line)])

    assert _field_value(data, label) == value
    assert not _no_data_message(data)


# ---------------------------------------------------------------------------
# F5: repeated labels are safe when the template already disambiguates them.


def test_f5_repeated_total_is_disambiguated_by_its_template_statement_column():
    grid = B._grid({
        "0,0": "Metric",
        "0,1": "Income Statement",
        "0,2": "Statement of Retained Earnings",
        "1,0": "Total",
    })
    lines = [
        "Income Statement",
        "Revenue 900.00",
        "Total 900.00",
        "Statement of Retained Earnings",
        "Opening balance 100.00",
        "Total 150.00",
    ]
    data = _run(
        lines,
        grid,
        doc_type="financial_statement",
        fields=[
            ("Total", 0, "900.00", lines[2]),
            ("Total", 1, "150.00", lines[5]),
        ],
    )

    refs = [field["ref"] for field in B._slots(grid)["fields"]
            if field["row_label"] == "Total"]
    assert len(refs) == 2
    assert [data["extracted_fields"][ref] for ref in refs] == ["900.00", "150.00"]
    assert all(data["validation"]["confidence_map"][ref] != "low" for ref in refs)
    assert not any("ambiguous" in flag["reason"].casefold()
                   for flag in B._flags(data))


def test_f5_total_in_two_declared_tables_stays_in_its_own_band():
    grid = B._grid(
        {
            "0,0": "Description", "0,1": "Total",
            "5,0": "Description", "5,1": "Total",
        },
        regions=[
            {"type": "table", "name": "Services", "orientation": "rows",
             "r1": 0, "c1": 0, "r2": 3, "c2": 1},
            {"type": "table", "name": "Goods", "orientation": "rows",
             "r1": 5, "c1": 0, "r2": 8, "c2": 1},
        ],
    )
    tables = B._slots(grid)["tables"]
    lines = [
        "SERVICES", "Description Total", "Consulting 600.00",
        "GOODS", "Description Total", "Parts 250.00",
    ]
    answers = {
        tables[0]["name"]: [{"cells": {"Description": "Consulting", "Total": "600.00"},
                              "source": lines[2], "page": 1}],
        tables[1]["name"]: [{"cells": {"Description": "Parts", "Total": "250.00"},
                              "source": lines[5], "page": 1}],
    }
    data = _run(lines, grid, tables=answers, doc_type="invoice")

    assert data[f"{tables[0]['name']}_rows"][0]["Total"] == "600.00"
    assert data[f"{tables[1]['name']}_rows"][0]["Total"] == "250.00"
    assert not any("ambiguous" in flag["reason"].casefold()
                   for flag in B._flags(data))


def test_f5_balance_sheet_and_income_statement_with_different_labels_are_clear():
    lines = [
        "Balance Sheet",
        "Total Assets 420,000.00",
        "Income Statement",
        "Net Income 38,400.00",
    ]
    grid = B._scalar_grid("Total Assets", "Net Income")
    data = _run(
        lines,
        grid,
        doc_type="financial_statement",
        fields=[
            ("Total Assets", 0, "420,000.00", lines[1]),
            ("Net Income", 0, "38,400.00", lines[3]),
        ],
    )

    assert _field_value(data, "Total Assets") == "420,000.00"
    assert _field_value(data, "Net Income") == "38,400.00"
    assert not any("ambiguous" in flag["reason"].casefold()
                   for flag in B._flags(data))


# ---------------------------------------------------------------------------
# E9: equal columns can be intentional.


def test_e9_payee_and_description_may_legitimately_be_identical():
    headers = ["Date", "Payee", "Description", "Amount"]
    grid = _table_grid(headers, name="Transactions")
    rows = [
        {"Date": "01/11/2026", "Payee": "Mesa Water", "Description": "Mesa Water", "Amount": "84.20"},
        {"Date": "02/11/2026", "Payee": "Valley Gas", "Description": "Valley Gas", "Amount": "61.10"},
    ]
    sources = [
        "01/11/2026 Mesa Water Mesa Water 84.20",
        "02/11/2026 Valley Gas Valley Gas 61.10",
    ]
    table, answers = _table_answer(grid, rows, sources)
    data = _run(["Date Payee Description Amount", *sources], grid,
                tables=answers, doc_type="bank_statement")

    assert [row["Description"] for row in _rows(data, table)] == [
        "Mesa Water", "Valley Gas",
    ]
    assert data["validation"]["copied_column_count"] == 0


def test_e9_equal_or_empty_debit_and_credit_columns_are_not_cleared():
    headers = ["Reference", "Debit", "Credit"]
    grid = _table_grid(headers, name="Journal")
    rows = [
        {"Reference": "Transfer A", "Debit": "125.00", "Credit": "125.00"},
        {"Reference": "Memo only", "Debit": "", "Credit": ""},
    ]
    sources = ["Transfer A 125.00 125.00", "Memo only"]
    table, answers = _table_answer(grid, rows, sources)
    data = _run(["Reference Debit Credit", *sources], grid,
                tables=answers, doc_type="other")

    got = _rows(data, table)
    assert [(row["Debit"], row["Credit"]) for row in got] == [
        ("125.00", "125.00"), ("", ""),
    ]
    assert data["validation"]["copied_column_count"] == 0


def test_e9_two_date_columns_may_legitimately_be_equal():
    headers = ["Order", "Order Date", "Delivery Date"]
    grid = _table_grid(headers, name="Orders")
    rows = [
        {"Order": "A-100", "Order Date": "01/11/2026", "Delivery Date": "01/11/2026"},
        {"Order": "A-101", "Order Date": "03/11/2026", "Delivery Date": "03/11/2026"},
    ]
    sources = [
        "A-100 01/11/2026 01/11/2026",
        "A-101 03/11/2026 03/11/2026",
    ]
    table, answers = _table_answer(grid, rows, sources)
    data = _run(["Order Order Date Delivery Date", *sources], grid,
                tables=answers, doc_type="purchase_order")

    assert [row["Delivery Date"] for row in _rows(data, table)] == [
        "01/11/2026", "03/11/2026",
    ]
    assert data["validation"]["copied_column_count"] == 0


# ---------------------------------------------------------------------------
# E11/E12: notation and address normalisation.


def test_e11_trailing_minus_grounds_and_exports_as_a_negative_amount():
    from tests.test_run_c_adversarial import document, round_trip

    line = "Payroll adjustment 46.32-"
    grid = B._scalar_grid("Payroll Adjustment")
    data = _run(["PAYROLL REGISTER", line], grid, doc_type="payslip",
                fields=[("Payroll Adjustment", 0, "-46.32", line)])

    ref = B._slots(grid)["fields"][0]["ref"]
    assert data["extracted_fields"][ref] == "-46.32"
    assert data["validation"]["confidence_map"][ref] != "low"
    sheet = round_trip([document(data)], grid)["Results"]
    assert sheet["B1"].value == pytest.approx(-46.32)


def test_e12_address_parts_in_a_different_normal_order_still_ground():
    lines = [
        "Northwind Trading BV",
        "1017 ZX Amsterdam",
        "Keizersgracht 391",
        "Netherlands",
    ]
    printed = "1017 ZX Amsterdam Keizersgracht 391 Netherlands"
    normalised = "Keizersgracht 391, 1017 ZX Amsterdam, Netherlands"
    grid = B._scalar_grid("Vendor Address")
    data = _run(lines, grid, doc_type="invoice",
                fields=[("Vendor Address", 0, normalised, printed)])

    ref = B._slots(grid)["fields"][0]["ref"]
    assert data["extracted_fields"][ref] == normalised
    assert data["validation"]["confidence_map"][ref] != "low"
    assert not B._flags(data)


def test_e12_provenance_helper_does_not_self_certify_a_cross_column_address():
    from tests.test_provenance import _on_page

    page = (
        "Keizersgracht 391  Other Vendor\n"
        "1017 ZX Amsterdam  500 Market Street\n"
        "Netherlands  United States"
    )
    mixed_parties = "Keizersgracht 391 500 Market Street United States"

    assert not _on_page(mixed_parties, page)


# ---------------------------------------------------------------------------
# E14: one document's notation must decide an otherwise ambiguous separator.


@pytest.mark.parametrize(
    "lines,values,expected",
    [
        (
            ["EUROPEAN INVOICE", "Subtotal EUR 1.234,56", "Service fee EUR 15,250"],
            ("1.234,56", "15,250"),
            (1234.56, 15.25),
        ),
        (
            ["UK INVOICE", "Subtotal GBP 1,234.56", "Project total GBP 15,250"],
            ("1,234.56", "15,250"),
            (1234.56, 15250.0),
        ),
    ],
    ids=["european-comma-decimal", "non-us-comma-thousands"],
)
def test_e14_document_notation_controls_ambiguous_thousands(lines, values, expected):
    from tests.test_run_c_adversarial import document, round_trip

    grid = B._scalar_grid("Subtotal", "Project Total")
    data = _run(
        lines,
        grid,
        doc_type="invoice",
        fields=[
            ("Subtotal", 0, values[0], lines[1]),
            ("Project Total", 0, values[1], lines[2]),
        ],
    )
    sheet = round_trip([document(data)], grid)["Results"]

    assert sheet["B1"].value == pytest.approx(expected[0])
    assert sheet["B2"].value == pytest.approx(expected[1])
