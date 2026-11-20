"""Blind acceptance tests made from the batch-1 staging exports (jobs 40-55).

Model answers are scripted from the values and source quotes stored in the
real XLSX comments.  Every answer is run through ``run_slot_extraction`` and,
where formatting matters, the production slot workbook writer.  No provider
or remote-service seam is installed.
"""
from __future__ import annotations

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from tests.contract import run_a_driver as D  # bootstraps production imports

import llm_contract as C  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
PDF_ROOT = ROOT / "tests" / "fixtures" / "acceptance" / "source_docs"
EXPORT_ROOT = ROOT / "local_docs" / "batch1_exports"
ITEM_1 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 1 — an unprinted remit bank must remain empty")
ITEM_2 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 2 — W-2 values and marks must stay in their printed boxes")
ITEM_3 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 3 — an uncoded Box 14 entry must not move into Box 12")
ITEM_4 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 4 — identifiers stay exact text and money keeps cents")
ITEM_5 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 5 — a page-one-only table cannot be silently complete")
ITEM_6 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 6 — split state/local rows must merge or flag")
ITEM_7 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 7 — values visibly on the page must not be marked Low")
ITEM_8 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 8 — blank fillable form boxes are not missing line items")
ITEM_9 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 9 — Legend mark counts must equal marked cells")
ITEM_10 = pytest.mark.xfail(
    strict=True, reason="BATCH1 ITEM 10 — every unambiguous date slot exports as a real date")
PDFS = {
    "bank": "bank_statement/flowparse_bank_us.pdf",
    "card": "credit_card/flowparse_card_us.pdf",
    "invoice": "invoice/flowparse_invoice_tax.pdf",
    "po": "purchase_order/flowparse_po.pdf",
    "mammoth": "bank_statement/mammoth_2pg.pdf",
    "cafe": "receipt_pdf/flowparse_cafe.pdf",
    "w2_blank": "w2/irs_w2_2012.pdf",
    "mcguire": "w2/irs6744_w2_mcguire.pdf",
    "pitt": "w2/pitt_sample_w2.pdf",
    "int1099": "1099/irs_1099int_mod3.pdf",
    "brokerage": "1099/irs6744_brokerage_1099DIV_MISC_INT_B.pdf",
}


def _pdf(name: str) -> Path:
    path = PDF_ROOT / PDFS[name]
    assert path.is_file(), f"required acceptance PDF is missing: {path}"
    return path


@lru_cache(maxsize=None)
def _document(name: str):
    from core.preprocessor import preprocess_file

    return preprocess_file(_pdf(name))


def _line(document, *needles: str, page: int | None = None,
          occurrence: int = 0) -> tuple[str, int]:
    wanted = [needle.casefold() for needle in needles]
    seen = 0
    for page_index, lines in enumerate(document.page_lines, start=1):
        if page is not None and page_index != page:
            continue
        for words in lines:
            text = " ".join(str(word.get("text", "")) for word in words).strip()
            folded = text.casefold()
            if text and all(needle in folded for needle in wanted):
                if seen == occurrence:
                    return text, page_index
                seen += 1
    raise AssertionError(f"source line not found: {needles!r}")


def _grid(cells: dict[str, str], *, regions: list[dict] | None = None) -> dict:
    return {
        "cells": {key: {"value": value, "style": {}}
                  for key, value in cells.items()},
        "merges": {},
        "colWidths": [],
        "repeatRows": [],
        "regions": regions or [],
    }


def _scalar_grid(*labels: str) -> dict:
    return _grid({f"{row},0": label for row, label in enumerate(labels)})


def _slots(grid: dict) -> dict:
    from slot_extractor import enumerate_slots

    return enumerate_slots(grid)


def _field_id(grid: dict, label: str, occurrence: int = 0) -> str:
    ids = [field["slot_id"] for field in _slots(grid)["fields"]
           if field["row_label"] == label]
    assert len(ids) > occurrence, (label, _slots(grid)["fields"])
    return ids[occurrence]


def _answer(fields: dict | None = None, tables: dict | None = None) -> dict:
    return {"fields": fields or {}, "tables": tables or {}}


def _run_pdf(name: str, grid: dict, answer: dict, *, doc_type: str) -> dict:
    from slot_extractor import run_slot_extraction

    document = _document(name)

    def extract(**_kwargs):
        parsed = copy.deepcopy(answer)
        return LLMResponse(
            raw_text=json.dumps(parsed), parsed_json=parsed, success=True,
            model_used="offline-batch1-scripted",
        )

    page_count = len(document.page_texts)
    with C.collect_attempts(fresh=True):
        result = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)),
            _pdf(name), {"layout": grid}, None,
            page_images=[],
            doc_text=document.extracted_text,
            doc_text_pages=document.page_texts,
            file_type=document.file_type,
            default_doc_type=doc_type,
            start=0.0,
            page_lines=document.page_lines,
            page_origins={i + 1: origin
                          for i, origin in enumerate(document.page_origins)},
            page_numbers=list(range(1, page_count + 1)),
            widget_values=document.widget_values,
            form_fields=document.form_fields,
            unreadable={
                "ocr_failed": document.ocr_failed_pages,
                "ocr_zero": document.ocr_zero_word_pages,
            },
        )[0]
    return result.extracted_data


def _value(data: dict, label: str) -> str:
    entry = (data.get("extracted_data") or {}).get(label)
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return str(entry or "")


def _flags(data: dict) -> list[dict]:
    return list((data.get("validation") or {}).get("flagged_fields") or [])


def _visible_review_text(data: dict) -> str:
    return " ".join(
        [f"{item.get('ref', '')} {item.get('reason', '')} {item.get('value', '')}"
         for item in _flags(data)]
        + [str(item.get("text") or "") for item in data.get("attention") or []]
    ).casefold()


def _write(data: dict, grid: dict, filename: str, *, documents=None):
    from app.services.excel_slot import _write_slot_excel

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    docs = documents or [SimpleNamespace(
        filename=filename,
        get_extracted_data=lambda: data,
    )]
    _write_slot_excel(
        sheet, docs, grid, grid["cells"], openpyxl,
        provenance=False, marks=True, audit=False,
    )
    return workbook


def _label_values(sheet, label: str):
    found = []
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value == label:
                found.append(sheet.cell(row=cell.row, column=cell.column + 1))
    return found


def _is_open(data: dict, ref: str) -> bool:
    # Scripted answers use public F<n> ids; stored review state uses the cell
    # ref.  Accept either so a negative-control assertion cannot miss a real
    # flag merely because it looked in the request namespace.
    ref = next((str(field.get("ref")) for field in
                (data.get("slot_map") or {}).get("fields") or []
                if str(field.get("slot_id")) == str(ref)), str(ref))
    provenance = (data.get("field_provenance") or {}).get(ref) or {}
    if provenance.get("review_required"):
        return True
    label = next((str(field.get("row_label")) for field in
                  (data.get("slot_map") or {}).get("fields") or []
                  if str(field.get("ref")) == ref), "")
    return any(str(flag.get("ref")) in {ref, label} for flag in _flags(data))


def test_01_invoice_vendor_name_is_not_invented_as_remit_bank():
    document = _document("invoice")
    source, page = _line(document, "Payment within 30 days", "Harwood")
    grid = _scalar_grid("Remit To Bank")
    answer = _answer(fields={_field_id(grid, "Remit To Bank"): {
        "value": "Harwood Design Studio Ltd", "source": source, "page": page,
    }})

    data = _run_pdf("invoice", grid, answer, doc_type="invoice")
    assert _value(data, "Remit To Bank") == ""


def test_02_w2_cross_box_value_and_checkbox_are_not_accepted():
    document = _document("pitt")
    box12_source, page = _line(document, "E", "4107.00", page=1)
    marks_source, marks_page = "13 Statemp.Ret.plan3rdpartysickpay X", 1
    grid = _scalar_grid(
        "Box 11 Nonqualified Plans",
        "Box 13 Statutory Employee",
        "Box 13 Retirement Plan",
    )
    answer = _answer(fields={
        _field_id(grid, "Box 11 Nonqualified Plans"): {
            "value": "4107", "source": box12_source, "page": page},
        _field_id(grid, "Box 13 Statutory Employee"): {
            "value": "X", "source": "X", "page": marks_page},
        _field_id(grid, "Box 13 Retirement Plan"): {
            "value": "X", "source": marks_source, "page": marks_page},
    })

    data = _run_pdf("pitt", grid, answer, doc_type="w2")
    problems = []
    if _value(data, "Box 11 Nonqualified Plans") != "":
        problems.append("Box 11 retained the Box 12a value")
    if _value(data, "Box 13 Statutory Employee") != "":
        problems.append("the retirement-plan X was copied to Statutory Employee")
    if _value(data, "Box 13 Retirement Plan").upper() != "X":
        problems.append("Retirement Plan lost the printed X")
    assert not problems, problems


def test_03_box14_entry_never_moves_to_an_uncoded_box12_row():
    document = _document("pitt")
    source, page = _line(document, "52.00", "14X", page=1)
    grid = _grid(
        {"0,0": "Box 12 Code", "0,1": "Box 12 Amount"},
        regions=[{"type": "table", "name": "Box 12 Codes", "orientation": "rows",
                  "r1": 0, "c1": 0, "r2": 3, "c2": 1}],
    )
    table = _slots(grid)["tables"][0]
    answer = _answer(tables={table["name"]: [{
        "cells": {"Box 12 Code": "", "Box 12 Amount": "52.00"},
        "source": source, "page": page,
    }]})

    data = _run_pdf("pitt", grid, answer, doc_type="w2")
    rows = data.get(f"{table['name']}_rows") or []
    moved = any(str(row.get("Box 12 Amount") or "").replace(".00", "") == "52"
                for row in rows)
    visible = any(word in _visible_review_text(data)
                  for word in ("extra", "no slot", "box 14", "uncoded", "code"))
    assert not moved and visible, {"rows": rows, "review": _visible_review_text(data)}


def test_04_identifiers_remain_text_and_money_keeps_two_decimals():
    document = _document("pitt")
    control_source, page = _line(document, "0000005712UUQ", "CKR5", page=1)
    local_source, local_page = _line(document, "700102", "478.08", page=1)
    money_source, money_page = _line(document, "E", "4107.00", page=1)
    grid = _scalar_grid("Control Number", "Locality Name", "Box 12 Amount")
    answer = _answer(fields={
        _field_id(grid, "Control Number"): {
            "value": "0000005712UUQ", "source": control_source, "page": page},
        _field_id(grid, "Locality Name"): {
            "value": "700102", "source": local_source, "page": local_page},
        _field_id(grid, "Box 12 Amount"): {
            "value": "4107", "source": money_source, "page": money_page},
    })

    data = _run_pdf("pitt", grid, answer, doc_type="w2")
    workbook = _write(data, grid, "pitt_sample_w2.pdf")
    sheet = workbook.active
    control = _label_values(sheet, "Control Number")[0]
    locality = _label_values(sheet, "Locality Name")[0]
    money = _label_values(sheet, "Box 12 Amount")[0]
    problems = []
    if _value(data, "Control Number") != "0000005712 UUQ":
        problems.append("control-number separator was not restored")
    if not (control.data_type == "s" and control.value == "0000005712 UUQ"):
        problems.append(f"control number exported as {control.value!r}/{control.data_type}")
    if "CKR5" in str(control.value) or "16260" in str(control.value):
        problems.append("control number absorbed adjacent CKR5/16260 text")
    if not (locality.data_type == "s" and locality.value == "700102"):
        problems.append(f"locality exported as {locality.value!r}/{locality.data_type}")
    if not (money.value == 4107 and money.number_format == "#,##0.00"):
        problems.append(f"money exported as {money.value!r}/{money.number_format!r}")
    assert not problems, problems


def _mammoth_page_one_answer(grid: dict) -> tuple[dict, dict]:
    document = _document("mammoth")
    table = _slots(grid)["tables"][0]
    rows = []
    for words in document.page_lines[0]:
        source = " ".join(str(word.get("text", "")) for word in words).strip()
        match = re.match(r"^(08/\d\d/2026)\s+(.+)$", source)
        if not match:
            continue
        pieces = match.group(2).rsplit(" ", 2)
        description = pieces[0]
        amount = pieces[-2] if len(pieces) >= 2 else ""
        rows.append({
            "cells": {"Date": match.group(1), "Description": description,
                      "Amount": amount},
            "source": source, "page": 1,
        })
    assert len(rows) == 37, "the real model returned exactly page 1's 37 rows"
    return table, _answer(tables={table["name"]: rows})


def test_05_page_one_only_statement_is_recovered_or_needs_attention():
    grid = _grid(
        {"0,0": "Date", "0,1": "Description", "0,2": "Amount"},
        regions=[{"type": "table", "name": "Transactions", "orientation": "rows",
                  "r1": 0, "c1": 0, "r2": 40, "c2": 2}],
    )
    table, answer = _mammoth_page_one_answer(grid)
    data = _run_pdf("mammoth", grid, answer, doc_type="bank_statement")
    rows = data.get(f"{table['name']}_rows") or []
    recovered = len(rows) >= 48 and any(str(row.get("Date")) == "09/04/2026"
                                        for row in rows)
    visible = _visible_review_text(data)
    explicit = str(data.get("document_state") or "").upper() == "NEEDS_ATTENTION" and any(
        word in visible for word in ("page", "row", "incomplete", "missing", "11"))
    assert recovered or explicit


def _brokerage_blank_form_type() -> tuple[dict, dict]:
    grid = _scalar_grid("Form Type", "Tax Year", "Payer Name")
    answer = _answer(fields={
        _field_id(grid, "Form Type"): {
            "value": "", "source": "Form 1099-DIV* 2026 Dividends and Distributions",
            "page": 1},
        _field_id(grid, "Tax Year"): {
            "value": "2026", "source": "2026 TAX REPORTING STATEMENT", "page": 1},
        _field_id(grid, "Payer Name"): {
            "value": "XYZ Investments", "source": "XYZ Investments", "page": 1},
    })
    return grid, answer


def test_06a_second_1099_form_type_is_filled_or_visibly_flagged():
    grid, answer = _brokerage_blank_form_type()
    data = _run_pdf("brokerage", grid, answer, doc_type="form_1099")
    ref = _field_id(grid, "Form Type")
    assert _value(data, "Form Type") or _is_open(data, ref)


def test_06b_same_1099_answer_has_identical_single_and_combined_blocks():
    grid, answer = _brokerage_blank_form_type()
    brokerage = _run_pdf("brokerage", grid, answer, doc_type="form_1099")
    int_data = _run_pdf("int1099", grid, _answer(fields={
        _field_id(grid, "Form Type"): {
            "value": "1099-INT", "source": "Form 1099-INT", "page": 1},
        _field_id(grid, "Tax Year"): {"value": "2014", "source": "2014", "page": 1},
        _field_id(grid, "Payer Name"): {
            "value": "FIRST FEDERAL BANK OF ANYTOWN",
            "source": "form field PAYER'S name", "page": 1},
    }), doc_type="form_1099")
    single = _write(brokerage, grid, "brokerage.pdf")
    docs = [
        SimpleNamespace(filename="irs_1099int_mod3.pdf",
                        get_extracted_data=lambda: int_data),
        SimpleNamespace(filename="brokerage.pdf",
                        get_extracted_data=lambda: brokerage),
    ]
    combined = _write(brokerage, grid, "brokerage.pdf", documents=docs)
    one = _label_values(single.active, "Form Type")[0]
    two = _label_values(combined.active, "Form Type")[1]
    assert (one.value, one.fill.fgColor.rgb, bool(one.comment)) == (
        two.value, two.fill.fgColor.rgb, bool(two.comment))


def test_06c_split_state_local_row_is_merged_or_visibly_flagged():
    source, page = (
        "15 State Employer's state ID no. 16 State wages, tips, etc. "
        "PA XXXX5369 47808.35 17 State income tax 18 Local wages, tips, etc. "
        "1467.72 47808.35 19 Local income tax 20 Locality name 478.08 700102",
        1,
    )
    headers = ["State", "Employer State ID", "State Wages", "State Income Tax",
               "Local Wages", "Local Income Tax", "Locality Name"]
    grid = _grid(
        {f"0,{column}": header for column, header in enumerate(headers)},
        regions=[{"type": "table", "name": "State and Local", "orientation": "rows",
                  "r1": 0, "c1": 0, "r2": 4, "c2": 6}],
    )
    table = _slots(grid)["tables"][0]
    answer = _answer(tables={table["name"]: [
        {"cells": {"State": "PA", "Employer State ID": "XXXX5369",
                   "State Wages": "47808.35", "State Income Tax": "1467.72"},
         "source": source, "page": page},
        {"cells": {"Local Wages": "47808.35", "Local Income Tax": "478.08"},
         "source": source, "page": page},
        {"cells": {"Locality Name": "700102"}, "source": source, "page": page},
    ]})
    data = _run_pdf("pitt", grid, answer, doc_type="w2")
    rows = data.get(f"{table['name']}_rows") or []
    merged = len(rows) == 1 and all(str(rows[0].get(header) or "") for header in headers)
    assert merged or any(word in _visible_review_text(data)
                         for word in ("split", "partial", "row", "incomplete", "missing"))


def _assert_no_open_refs(data: dict, refs: list[str], case: str, failures: list[str]):
    bad = [ref for ref in refs if _is_open(data, ref)]
    if bad:
        failures.append(f"{case}: {bad} were incorrectly marked low/unverified")


def test_07_correct_values_are_not_low_but_real_errors_still_are():
    failures: list[str] = []

    # Jobs 53/54: the values are present after dot leaders in the source quote.
    dot_values = [
        ("INT Box 1 Interest Income", "70.00",
         "1 Interest Income ...........................................70.00"),
        ("INT Box 2 Early Withdrawal Penalty", "0.00",
         "2 Early Withdrawal Penalty ....................................0.00"),
        ("INT Box 3 US Savings Bond Interest", "0.00",
         "3 Interest on U.S. Savings Bonds and Treas. Obligations .............0.00"),
        ("INT Box 4 Federal Tax Withheld", "0.00",
         "4 Federal Income Tax Withheld .................................0.00"),
        ("INT Box 8 Tax-Exempt Interest", "0.00",
         "8 Tax-Exempt Interest ........................................0.00"),
        ("DIV Box 1a Total Ordinary Dividends", "300.00",
         "1a Total Ordinary Dividends ....................................300.00"),
        ("DIV Box 1b Qualified Dividends", "225.00",
         "1b Qualified Dividends .......................................225.00"),
        ("DIV Box 2a Capital Gain Distributions", "350.00",
         "2a Total Capital Gain Distributions (Includes 2b-2d) .............350.00"),
        ("DIV Box 2b Unrecaptured 1250 Gain", "0.00",
         "2b Capital Gains that represent Unrecaptured 1250 Gain ..............0.00"),
        ("DIV Box 2c Section 1202 Gain", "0.00",
         "2c Capital Gains that represent Section 1202 Gain ...................0.00"),
        ("DIV Box 4 Federal Tax Withheld", "0.00",
         "4 Federal Income Tax Withheld ...............................0.00"),
        ("DIV Box 5 Section 199A Dividends", "48.00",
         "5 Section 199A Dividends ....................................48.00"),
        ("DIV Box 7 Foreign Tax Paid", "0.00",
         "7 Foreign Tax Paid ...........................................0.00"),
    ]
    grid = _scalar_grid(*(label for label, _, _ in dot_values))
    answer = _answer(fields={
        _field_id(grid, label): {"value": value, "source": source, "page": 1}
        for label, value, source in dot_values
    })
    data = _run_pdf("brokerage", grid, answer, doc_type="form_1099")
    _assert_no_open_refs(data, [_field_id(grid, label) for label, _, _ in dot_values],
                         "dot leaders", failures)

    # Job 40: the answer quoted the header row, but each number is elsewhere
    # on the same page and must be grounded there before being marked Low.
    grid = _scalar_grid("Opening Balance", "Closing Balance",
                        "Total Deposits and Credits", "Total Withdrawals and Debits")
    header = "Beginning balance Withdrawals Deposits Ending balance"
    values = ["18,240.12", "20,376.00", "12,445.50", "10,309.62"]
    refs = [_field_id(grid, label) for label in
            ("Opening Balance", "Closing Balance", "Total Deposits and Credits",
             "Total Withdrawals and Debits")]
    data = _run_pdf("bank", grid, _answer(fields={
        ref: {"value": value, "source": header, "page": 1}
        for ref, value in zip(refs, values)
    }), doc_type="bank_statement")
    _assert_no_open_refs(data, refs, "bank summary", failures)

    # Job 42: line-break joins in quotes must compare like spaces.
    grid = _scalar_grid("Vendor Address", "Bill To Address")
    refs = [_field_id(grid, label) for label in ("Vendor Address", "Bill To Address")]
    data = _run_pdf("invoice", grid, _answer(fields={
        refs[0]: {
            "value": "14 Weavers Yard Shoreditch London E2 7DP United Kingdom",
            "source": "14 Weavers YardShoreditchLondon E2 7DPUnited Kingdom", "page": 1},
        refs[1]: {
            "value": "Unit 9 Quayside Business Park Bristol BS1 6QS United Kingdom",
            "source": "Unit 9Quayside Business ParkBristol BS1 6QSUnited Kingdom", "page": 1},
    }), doc_type="invoice")
    _assert_no_open_refs(data, refs, "joined addresses", failures)

    # Job 46: literal transaction descriptions occupy the Description column.
    document = _document("mammoth")
    atm_source, atm_page = _line(document, "ATM WITHDRAWAL", page=1)
    mobile_source, mobile_page = _line(document, "MOBILE DEPOSIT", page=1)
    grid = _grid(
        {"0,0": "Date", "0,1": "Description", "0,2": "Amount"},
        regions=[{"type": "table", "name": "Transactions", "orientation": "rows",
                  "r1": 0, "c1": 0, "r2": 3, "c2": 2}],
    )
    table = _slots(grid)["tables"][0]
    answer = _answer(tables={table["name"]: [
        {"cells": {"Date": "08/11/2026", "Description": "ATM WITHDRAWAL",
                   "Amount": "100.00"}, "source": atm_source, "page": atm_page},
        {"cells": {"Date": "08/11/2026", "Description": "MOBILE DEPOSIT",
                   "Amount": "500.00"}, "source": mobile_source, "page": mobile_page},
    ]})
    data = _run_pdf("mammoth", grid, answer, doc_type="bank_statement")
    if "different column" in _visible_review_text(data):
        failures.append("mammoth: ATM WITHDRAWAL/MOBILE DEPOSIT marked as another column")

    # Job 50: the name is visibly next to its W-2 label.
    document = _document("mcguire")
    source, page = _line(document, "Kim", "McGuire", page=1)
    grid = _scalar_grid("Box e Employee Name")
    ref = _field_id(grid, "Box e Employee Name")
    data = _run_pdf("mcguire", grid, _answer(fields={ref: {
        "value": "Kim McGuire", "source": source, "page": page,
    }}), doc_type="w2")
    _assert_no_open_refs(data, [ref], "Kim McGuire", failures)

    # Negative controls: real placement and absence errors still owe review.
    grid = _scalar_grid("Payer Name", "Recipient TIN")
    misplaced = _field_id(grid, "Payer Name")
    absent = _field_id(grid, "Recipient TIN")
    data = _run_pdf("brokerage", grid, _answer(fields={
        misplaced: {"value": "70.00", "source": dot_values[0][2], "page": 1},
        absent: {"value": "999-99-9999", "source": "Recipient ID No.", "page": 1},
    }), doc_type="form_1099")
    assert _is_open(data, misplaced), "a value taken from the wrong labelled box must flag"
    assert _is_open(data, absent), "a value absent from the page must flag"
    assert not failures, failures


def _w2_blank_grid() -> dict:
    cells = {
        "0,0": "Tax Year", "1,0": "Box a Employee SSN",
        "2,0": "Box b Employer EIN", "3,0": "Box c Employer Name",
        "5,0": "Box 12 Code", "5,1": "Box 12 Amount",
        "9,0": "State", "9,1": "Employer State ID", "9,2": "State Wages",
        "9,3": "State Income Tax", "9,4": "Local Wages",
        "9,5": "Local Income Tax", "9,6": "Locality Name",
    }
    return _grid(cells, regions=[
        {"type": "table", "name": "Box 12 Codes", "orientation": "rows",
         "r1": 5, "c1": 0, "r2": 7, "c2": 1},
        {"type": "table", "name": "State and Local", "orientation": "rows",
         "r1": 9, "c1": 0, "r2": 11, "c2": 6},
    ])


def test_08_fillable_blank_boxes_do_not_create_false_completeness_reasons():
    grid = _w2_blank_grid()
    slots = _slots(grid)
    fields = {
        field["slot_id"]: {"value": "", "source": "", "page": 1}
        for field in slots["fields"]
    }
    answer = _answer(fields=fields,
                     tables={table["name"]: [] for table in slots["tables"]})
    w2 = _run_pdf("w2_blank", grid, answer, doc_type="w2")
    w2_reasons = " ".join(str(item.get("text") or "")
                           for item in w2.get("attention") or []).casefold()
    failures = []
    if "about 2 line items" in w2_reasons:
        failures.append("blank W-2 reported about 2 line items")
    if "did not include the rows" in w2_reasons:
        failures.append("blank W-2 reported omitted rows")

    labels = [
        "Form Type", "Tax Year", "Payer Name", "Payer TIN", "Recipient Name",
        "Recipient TIN", "Account Number", "INT Box 1 Interest Income",
        "INT Box 2 Early Withdrawal Penalty", "INT Box 3 US Savings Bond Interest",
        "INT Box 4 Federal Tax Withheld", "INT Box 8 Tax-Exempt Interest",
        "DIV Box 1a Total Ordinary Dividends", "DIV Box 1b Qualified Dividends",
        "DIV Box 2a Capital Gain Distributions", "DIV Box 4 Federal Tax Withheld",
        "DIV Box 5 Section 199A Dividends", "DIV Box 7 Foreign Tax Paid",
    ]
    grid = _scalar_grid(*labels)
    values = {
        "Form Type": ("Form 1099-INT", "Form 1099-INT"),
        "Tax Year": ("2014", "2014"),
        "Payer Name": ("FIRST FEDERAL BANK OF ANYTOWN", "form field PAYER'S name"),
        "Payer TIN": ("10-0000002", "form field PAYER'S federal identification number"),
        "Recipient Name": ("TASHA MILLER", "form field RECIPIENT'S name"),
        "Recipient TIN": ("222-00-2222", "form field RECIPIENT'S identification number"),
        "INT Box 1 Interest Income": ("43.00", "form field 1 Interest income"),
    }
    answer = _answer(fields={
        _field_id(grid, label): {"value": values.get(label, ("", ""))[0],
                                 "source": values.get(label, ("", ""))[1], "page": 1}
        for label in labels
    })
    form1099 = _run_pdf("int1099", grid, answer, doc_type="form_1099")
    reasons = " ".join(str(item.get("text") or "")
                       for item in form1099.get("attention") or []).casefold()
    if "11 of 18 field slots are empty while the labels of 7 are printed" in reasons:
        failures.append("fillable 1099 reported its intentional blank boxes as missing")

    # Positive control: a text-layer value printed beside its label must not
    # disappear merely because the model returned an empty slot.
    grid = _scalar_grid("Invoice Number")
    ref = _field_id(grid, "Invoice Number")
    missed = D.run_synthetic(
        lambda **_kwargs: D.model_response(_answer(fields={ref: {
            "value": "", "source": "", "page": 1,
        }})),
        [["Invoice Number INV-900"]], grid=grid,
    )
    assert _is_open(missed, ref) or any(
        word in _visible_review_text(missed) for word in ("missing", "empty", "inv-900")
    )
    assert not failures, failures


def _legend_counts(workbook) -> tuple[int, int, int]:
    text = " ".join(str(cell.value) for row in workbook["Legend"].iter_rows()
                    for cell in row if cell.value is not None)
    match = re.search(r"(\d+) low\s+·\s+(\d+) unverified\s+·\s+"
                      r"(\d+) empty and flagged", text)
    assert match, text
    return tuple(int(value) for value in match.groups())


def _marked_counts(workbook) -> tuple[int, int, int]:
    colors = ("FFFFC7CE", "FFFFEB9C", "FFD9D9D9")
    counts = [0, 0, 0]
    for sheet in workbook.worksheets:
        if sheet.title == "Legend":
            continue
        for row in sheet.iter_rows():
            for cell in row:
                rgb = cell.fill.fgColor.rgb
                if rgb in colors:
                    counts[colors.index(rgb)] += 1
    return tuple(counts)


@ITEM_9
def test_09_each_real_legend_count_equals_cells_actually_marked():
    mismatches = {}
    for job in range(40, 56):
        path = EXPORT_ROOT / f"job_{job}_results.xlsx"
        assert path.is_file(), f"required real staging export is missing: {path}"
        workbook = openpyxl.load_workbook(path, data_only=False)
        legend = _legend_counts(workbook)
        marked = _marked_counts(workbook)
        if legend != marked:
            mismatches[job] = {"legend": legend, "marked": marked}
    assert not mismatches, mismatches


DATE_CASES = [
    (40, "bank", "Statement Period Start", "09/01/2026",
     ("09/01/2026", "09/30/2026"), "bank_statement"),
    (41, "card", "Statement Period Start", "09/15/2026",
     ("09/15/2026", "10/14/2026"), "credit_card_statement"),
    (42, "invoice", "Invoice Date", "14 Oct 2026",
     ("Issued", "14 Oct 2026"), "invoice"),
    (45, "po", "Order Date", "2026-10-05",
     ("2026-10-05",), "purchase_order"),
    (46, "mammoth", "Statement Period Start", "08/01/2026",
     ("08/01/2026", "08/31/2026"), "bank_statement"),
    (47, "cafe", "Receipt Date", "2026-10-21",
     ("2026-10-21",), "receipt"),
]
NON_DATE_JOBS = {43, 44, 48, 49, 50, 51, 52, 53, 54, 55}


def test_10_date_slots_export_as_real_dates():
    assert {case[0] for case in DATE_CASES} | NON_DATE_JOBS == set(range(40, 56))
    companions = {
        40: ("Statement Period End", "09/30/2026"),
        41: ("Statement Period End", "10/14/2026"),
        46: ("Statement Period End", "08/31/2026"),
    }
    failures = {}
    for job, name, label, printed, needles, doc_type in DATE_CASES:
        document = _document(name)
        source, page = _line(document, *needles)
        labels = [label] + ([companions[job][0]] if job in companions else [])
        grid = _scalar_grid(*labels)
        fields = {_field_id(grid, label): {
            "value": printed, "source": source, "page": page,
        }}
        if job in companions:
            companion_label, companion_value = companions[job]
            fields[_field_id(grid, companion_label)] = {
                "value": companion_value, "source": source, "page": page,
            }
        data = _run_pdf(name, grid, _answer(fields=fields), doc_type=doc_type)
        workbook = _write(data, grid, f"job_{job}.pdf")
        cell = _label_values(workbook.active, label)[0]
        if not cell.is_date or cell.number_format != "mm/dd/yyyy":
            failures[job] = (cell.value, cell.data_type, cell.number_format)
    assert not failures, failures


def test_10_ambiguous_date_stays_text_in_the_mock_export_path():
    grid = _scalar_grid("Invoice Date")
    ref = _field_id(grid, "Invoice Date")
    data = D.run_synthetic(
        lambda **_kwargs: D.model_response(_answer(fields={ref: {
            "value": "03/04/2026", "source": "Invoice Date 03/04/2026", "page": 1,
        }})),
        [["Invoice Date 03/04/2026"]], grid=grid,
    )
    workbook = _write(data, grid, "ambiguous-date.pdf")
    cell = _label_values(workbook.active, "Invoice Date")[0]
    assert cell.data_type == "s" and cell.value == "03/04/2026"
    assert cell.comment and "day and month could be swapped" in cell.comment.text.casefold()
