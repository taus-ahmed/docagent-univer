"""Batch 2: document-shaped failures at the post-model production seam.

Every model answer in this module is local and scripted.  The tests call
``run_slot_extraction`` (the same function the worker calls after a model
response) with the real PDF text/geometry.  No provider client or network seam
is installed.

The source corpus normally lives at ``local_docs/``.  The review workstation
keeps the same corpus beside the checkout under
``docagent-testdocs/DocAgent_testdocs``; ``_pdf`` accepts that location only as
a local fallback.  Missing source documents are errors, never skips.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from tests.contract import run_a_driver as D  # bootstraps production imports

import llm_contract as C  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
LOCAL_CORPUS = ROOT.parent / "docagent-testdocs" / "DocAgent_testdocs"
DOC_ROOTS = (ROOT / "local_docs", ROOT / "tests" / "local_docs", LOCAL_CORPUS)

DOCS = {
    "blank_po": "purchase_order/gallatin_po_4pg.pdf",
    "ou_explainer": "payslip/ou_check_stub.pdf",
    "saltlake_explainer": "payslip/saltlake_paycheck.pdf",
    "placeholders": "1099/virtus_1099b.pdf",
    "callouts": "bank_statement/fidelity_brokerage.pdf",
    "duplicate_bands": "expense_report/smartsheet_mileage.pdf",
    "statements": "financial_statements/tcnj_financials.pdf",
    "po_units": "purchase_order/portland_po_distributed.pdf",
    "long_bank": "bank_statement/carson_bank_6pg.pdf",
    "unreadable": "payslip/utah_paystub_1.pdf",
}


def _pdf(name: str) -> Path:
    relative = Path(DOCS[name])
    for root in DOC_ROOTS:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    if name == "statements":
        committed = (ROOT / "tests" / "fixtures" / "acceptance" /
                     "source_docs" / "financial_statements" /
                     "tcnj_financials.pdf")
        if committed.is_file():
            return committed
    searched = ", ".join(str(root / relative) for root in DOC_ROOTS)
    raise AssertionError(f"required local source PDF is missing: {searched}")


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
    raise AssertionError(
        f"source line occurrence {occurrence} not found: {needles!r} "
        f"in {_pdf_name(document)}"
    )


def _pdf_name(document) -> str:
    return str(getattr(document, "filename", "local PDF"))


def _grid(cells: dict[str, str], *, regions: list[dict] | None = None,
          col_widths: list[int] | None = None) -> dict:
    return {
        "cells": {key: {"value": value, "style": {}}
                  for key, value in cells.items()},
        "merges": {},
        "colWidths": col_widths or [],
        "repeatRows": [],
        "regions": regions or [],
    }


def _scalar_grid(*labels: str) -> dict:
    return _grid({f"{row},0": label for row, label in enumerate(labels)})


def _slots(grid: dict) -> dict:
    from slot_extractor import enumerate_slots

    return enumerate_slots(grid)


def _field_id(grid: dict, label: str, occurrence: int = 0) -> str:
    found = [field["slot_id"] for field in _slots(grid)["fields"]
             if field["row_label"] == label]
    assert len(found) > occurrence, (label, _slots(grid)["fields"])
    return found[occurrence]


def _answer(fields: dict | None = None, tables: dict | None = None) -> dict:
    return {"fields": fields or {}, "tables": tables or {}}


def _run_pdf(name: str, grid: dict, answer: dict, *, doc_type: str = "other") -> dict:
    """Replay one scripted answer through the real post-model pipeline."""
    from slot_extractor import run_slot_extraction

    document = _document(name)

    def extract(**_kwargs):
        parsed = copy.deepcopy(answer)
        return LLMResponse(
            raw_text=json.dumps(parsed), parsed_json=parsed, success=True,
            model_used="offline-batch2-scripted",
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


def _flag_text(data: dict) -> str:
    return " ".join(
        f"{item.get('ref', '')} {item.get('value', '')} {item.get('reason', '')}"
        for item in _flags(data)
    ).casefold()


def _assert_clear_no_data_state(data: dict) -> None:
    """Accept an explicit state or an equally explicit document-level note."""
    state = str(data.get("document_state") or "").upper()
    notes = " ".join(
        [str(item.get("text") or "") for item in data.get("attention") or []]
        + [str(note) for note in data.get("validation_notes") or []]
    ).casefold()
    assert state in {"BLANK", "EMPTY", "NO_DATA", "NO_DATA_FOUND"} or any(
        phrase in notes for phrase in ("blank form", "no filled", "no data")
    ), (state, notes)


def test_01_copied_unprinted_column_is_not_silent_and_description_survives():
    document = _document("po_units")
    source, page = _line(document, "00010", "1,175.00", page=1)
    grid = _grid(
        {"0,0": "Line", "0,1": "Description", "0,2": "Memo",
         "0,3": "Net Amount"},
        regions=[{"type": "table", "name": "Items", "orientation": "rows",
                  "r1": 0, "c1": 0, "r2": 2, "c2": 3}],
    )
    table = _slots(grid)["tables"][0]
    description = "overhead door svc UF 259266"
    answer = _answer(tables={table["name"]: [{
        "cells": {"Line": "00010", "Description": description,
                  "Memo": description, "Net Amount": "1,175.00"},
        "source": source, "page": page,
    }]})

    data = _run_pdf("po_units", grid, answer, doc_type="purchase_order")
    rows = data[f"{table['name']}_rows"]
    assert rows and rows[0]["Description"] == description
    memo = rows[0].get("Memo", "")
    assert not memo or "memo" in _flag_text(data), (
        "a copied column may be cleared or kept only when visibly flagged",
        rows[0], _flags(data),
    )


def test_02_blank_form_discards_underscores_and_inventions_without_slot_flags():
    document = _document("blank_po")
    date_source, date_page = _line(document, "Date:", "___", page=1)
    po_source, po_page = _line(document, "Purchase Order #", page=1)
    company_source, company_page = _line(document, "Company Name", page=1)
    underscore = re.search(r"_{3,}", date_source)
    assert underscore, date_source
    grid = _scalar_grid("Date", "Purchase Order Number", "Seller Company Name")
    answer = _answer(fields={
        _field_id(grid, "Date"): {
            "value": underscore.group(0), "source": date_source, "page": date_page},
        _field_id(grid, "Purchase Order Number"): {
            "value": "PO-9999", "source": po_source, "page": po_page},
        _field_id(grid, "Seller Company Name"): {
            "value": "ACME SUPPLY", "source": company_source, "page": company_page},
    })

    data = _run_pdf("blank_po", grid, answer, doc_type="purchase_order")
    assert data["extracted_fields"] == {}
    assert _flags(data) == []
    _assert_clear_no_data_state(data)


@pytest.mark.parametrize(
    "name,label,bad_value,needles",
    [
        ("ou_explainer", "Gross Pay", "8", ("8.", "Net pay")),
        ("saltlake_explainer", "Net Pay", "$0.00",
         ("amounts", "balance", "$0.00")),
    ],
    ids=["ou_check_stub", "saltlake_paycheck"],
)
def test_03_explainer_pages_do_not_become_pay_data(name, label, bad_value, needles):
    document = _document(name)
    source, page = _line(document, *needles)
    grid = _scalar_grid(label)
    answer = _answer(fields={_field_id(grid, label): {
        "value": bad_value, "source": source, "page": page,
    }})

    data = _run_pdf(name, grid, answer, doc_type="payslip")
    assert data["extracted_fields"] == {}
    assert data["document_state"] == "NEEDS_ATTENTION"
    assert data["attention"], "no-real-data documents need one document-level explanation"


def test_04_specimen_placeholders_are_not_real_payer_or_recipient_data():
    """Rule reading: conspicuous instructional/sample tokens in a specimen are
    placeholders, not identities.  ``MR A SAMPLE`` could be a legal name in
    isolation, so the rule relies on its context: the same specimen also says
    ``SAMPLE ... FORM``, ``FULL COMPANY NAME`` and ``ADD 1`` through ``ADD 5``.
    That contextual part is a product-policy choice and is intentionally made
    explicit here rather than treating the token ``SAMPLE`` as universally
    invalid.
    """
    document = _document("placeholders")
    recipient_source, recipient_page = _line(document, "MR A SAMPLE")
    payer_source, payer_page = _line(document, "FULL COMPANY NAME")
    address_source, address_page = _line(document, "ADD 1", "Payer")
    grid = _scalar_grid("Payer Name", "Recipient Name", "Payer Address")
    answer = _answer(fields={
        _field_id(grid, "Payer Name"): {
            "value": "FULL COMPANY NAME", "source": payer_source, "page": payer_page},
        _field_id(grid, "Recipient Name"): {
            "value": "MR A SAMPLE", "source": recipient_source,
            "page": recipient_page},
        _field_id(grid, "Payer Address"): {
            "value": "ADD 1", "source": address_source, "page": address_page},
    })

    data = _run_pdf("placeholders", grid, answer, doc_type="form_1099")
    assert data["extracted_fields"] == {}
    assert _flags(data) == []
    _assert_clear_no_data_state(data)


def test_05_numbered_callout_is_not_accepted_as_the_labelled_amount():
    document = _document("callouts")
    source, page = _line(document, "1", "Your Account Value", "$125,310.49")
    grid = _scalar_grid("Your Account Value")
    answer = _answer(fields={_field_id(grid, "Your Account Value"): {
        "value": "1", "source": source, "page": page,
    }})

    data = _run_pdf("callouts", grid, answer, doc_type="bank_statement")
    got = _value(data, "Your Account Value")
    assert got != "1", "the nearby 1 is a diagram callout, not an account value"
    if not got:
        assert "empty_flagged" in _flag_text(data), (
            "the page prints an account value, so clearing the callout must expose the miss",
            _flags(data),
        )


def test_06_duplicate_blank_band_labels_stay_empty_and_unassigned():
    # The source really contains two independent blank expense tables and two
    # TOTALS labels.  Supplying every requested slot/table as explicitly empty
    # prevents model-contract noise from masquerading as a content verdict.
    _document("duplicate_bands")
    grid = _grid(
        {
            "0,0": "Date", "0,1": "Mileage", "0,2": "Total",
            "3,0": "TOTALS",
            "5,0": "Date", "5,1": "Mileage", "5,2": "Total",
            "8,0": "TOTALS",
        },
        regions=[
            {"type": "table", "name": "Employee paid", "orientation": "rows",
             "r1": 0, "c1": 0, "r2": 2, "c2": 2},
            {"type": "table", "name": "Company paid", "orientation": "rows",
             "r1": 5, "c1": 0, "r2": 7, "c2": 2},
        ],
    )
    slots = _slots(grid)
    empty_fields = {field["slot_id"]: {"value": "", "source": "", "page": 1}
                    for field in slots["fields"]}
    empty_tables = {table["name"]: [] for table in slots["tables"]}

    data = _run_pdf("duplicate_bands", grid,
                    _answer(fields=empty_fields, tables=empty_tables),
                    doc_type="expense_report")
    assert data["extracted_fields"] == {}
    assert all(data.get(f"{table['name']}_rows") == [] for table in slots["tables"])
    assert _flags(data) == []
    assert data["attention"] == []
    assert data["document_state"] == "READY"


@pytest.mark.xfail(
    strict=True,
    reason=("Rule: repeated labels across multiple statements require a visible "
            "statement choice or ambiguity flag"),
)
def test_07_generic_net_income_does_not_silently_blend_multiple_statements():
    document = _document("statements")
    revenue_source, revenue_page = _line(document, "Service revenue", "$2,750")
    retained_source, retained_page = _line(
        document, "Net income", "945", page=1, occurrence=1,
    )
    assert "$" not in retained_source, (
        "the bad answer must cite retained earnings, not the service income statement",
        retained_source,
    )
    grid = _scalar_grid("Service revenue", "Net income")
    net_ref = _field_id(grid, "Net income")
    answer = _answer(fields={
        _field_id(grid, "Service revenue"): {
            "value": "$2,750", "source": revenue_source, "page": revenue_page,
        },
        net_ref: {
            # Same number, wrong statement section: this is the subtle blend.
            "value": "945", "source": retained_source, "page": retained_page,
        },
    })

    data = _run_pdf("statements", grid, answer, doc_type="income_statement")
    assert _value(data, "Service revenue") in {"$2,750", "2,750"}
    net_value = _value(data, "Net income")
    net_source = str(
        ((data.get("field_provenance") or {}).get(net_ref) or {}).get("source") or ""
    )
    visible = _flag_text(data) + " " + " ".join(
        str(item.get("text") or "") for item in data.get("attention") or [])
    visible = visible.casefold()
    assert (not net_value or "$945" in net_source
            or any(word in visible for word in
                   ("ambiguous", "multiple", "statement", "region"))), (
        "Service revenue chooses the service income statement, so Net income "
        "cannot silently cite the retained-earnings section merely because its "
        "number is the same",
        net_value, net_source, _flags(data), data.get("attention"),
    )


def test_08_quantity_unit_price_and_net_are_literal_not_recomputed():
    document = _document("po_units")
    source, page = _line(document, "00010", "1,175.00", "USD", page=1)
    headers = ["Line", "Material / Material Description", "Quantity", "UM",
               "Unit Price", "Net Amount"]
    grid = _grid(
        {f"0,{column}": header for column, header in enumerate(headers)},
        regions=[{"type": "table", "name": "Line items", "orientation": "rows",
                  "r1": 0, "c1": 0, "r2": 3, "c2": len(headers) - 1}],
    )
    table = _slots(grid)["tables"][0]
    cells = {
        "Line": "00010",
        "Material / Material Description": "386353 overhead door svc UF 259266",
        "Quantity": "1,175.00",
        "UM": "USD",
        "Unit Price": "1.00",
        "Net Amount": "1,175.00",
    }
    data = _run_pdf(
        "po_units", grid,
        _answer(tables={table["name"]: [{"cells": cells, "source": source,
                                          "page": page}]}),
        doc_type="purchase_order",
    )
    row = data[f"{table['name']}_rows"][0]
    assert {key: row[key] for key in ("Quantity", "UM", "Unit Price", "Net Amount")} == {
        "Quantity": "1,175.00", "UM": "USD",
        "Unit Price": "1.00", "Net Amount": "1,175.00",
    }


def _bank_case():
    headers = ["Date", "Description", "Debits", "Credits"]
    grid = _grid(
        {f"0,{column}": header for column, header in enumerate(headers)},
        regions=[{"type": "table", "name": "Transactions", "orientation": "rows",
                  "r1": 0, "c1": 0, "r2": 30, "c2": 3}],
    )
    table = _slots(grid)["tables"][0]
    rows, lines = [], ["Date Description Debits Credits"]
    for index in range(64):
        date = f"07/{(index % 28) + 1:02}/2019"
        description = f"TX{index + 1:02}"
        debit = "14,365.21" if index == 60 else "0.00"
        credit = "18,041.50" if index == 61 else "0.00"
        source = f"{date} {description} {debit} {credit}"
        rows.append({"cells": {"Date": date, "Description": description,
                                "Debits": debit, "Credits": credit},
                     "source": source, "page": 1})
        lines.append(source)
    lines += ["Total Debits 14,365.21", "Total Credits 18,041.50"]
    return grid, table, rows, lines


def _run_bank_rows(rows: list[dict], grid: dict, table: dict, lines: list[str]) -> dict:
    answer = _answer(tables={table["name"]: copy.deepcopy(rows)})
    return D.run_synthetic(
        lambda **_kwargs: D.model_response(copy.deepcopy(answer)),
        [lines], grid=grid,
    )


def test_09_long_table_flags_short_and_duplicate_answers_and_grows_past_30_rows():
    # The actual six-page statement independently supplies the document facts.
    document = _document("long_bank")
    assert len(document.page_texts) == 6
    text = " ".join(document.page_texts)
    assert all(number in text for number in
               ("$3,005.93", "$18,041.50", "$14,365.21", "$6,682.22"))
    assert "Deposits/credits 10" in text
    assert "Checks/withdrawals 54" in text
    assert 10 + 54 == 64
    assert (Decimal("3005.93") + Decimal("18041.50")
            - Decimal("14365.21")) == Decimal("6682.22")

    grid, table, rows, lines = _bank_case()

    short = _run_bank_rows(rows[:60], grid, table, lines)
    short_visible = _flag_text(short) + " " + " ".join(
        item.get("text", "") for item in short.get("attention") or [])
    assert "row_sum_mismatch" in short_visible or "sum to" in short_visible

    duplicated = _run_bank_rows(rows + [copy.deepcopy(rows[0])], grid, table, lines)
    assert duplicated["validation"]["dropped_row_count"] == 1
    assert "duplicate" in _flag_text(duplicated) or "already used" in _flag_text(duplicated)
    assert len(duplicated[f"{table['name']}_rows"]) == 64

    complete = _run_bank_rows(rows, grid, table, lines)
    assert len(complete[f"{table['name']}_rows"]) == 64
    from app.services.excel_slot import _write_slot_excel

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    doc = SimpleNamespace(
        filename="carson_bank_6pg.pdf",
        get_extracted_data=lambda: complete,
    )
    _write_slot_excel(sheet, [doc], grid, grid["cells"], openpyxl,
                      provenance=False, marks=False, audit=False)
    assert sheet.cell(row=65, column=2).value == "TX64", (
        "one header plus 64 actual rows must grow beyond the 30 reserved rows",
        sheet.max_row,
    )


def test_10_garbled_scan_value_is_flagged_or_flagged_empty_not_silent():
    document = _document("unreadable")
    source, page = _line(document, "Pay Rate", "$8,449.50")
    grid = _scalar_grid("Pay Rate")
    answer = _answer(fields={_field_id(grid, "Pay Rate"): {
        "value": "$99,999.99", "source": source, "page": page,
    }})

    data = _run_pdf("unreadable", grid, answer, doc_type="payslip")
    got = _value(data, "Pay Rate")
    visible_flag = any(
        flag.get("ref") == "Pay Rate" or "Pay Rate" in str(flag.get("ref", ""))
        for flag in _flags(data)
    )
    assert not got or visible_flag
    assert data["document_state"] != "READY"

