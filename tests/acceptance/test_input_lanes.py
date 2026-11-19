from __future__ import annotations

import re

import pytest

from tests.contract import names
from tests.contract.adapter import (
    assert_non_ready_with_reason,
    page_ledger_of,
    resolve_callable,
    state_of,
)
from tests.contract.run_a_driver import model_response, run_synthetic, words


@pytest.mark.parametrize(
    "relative_path,needles",
    [
        # The AcroForm widget and model-input text contain "10535" verbatim;
        # the old "10,535" expectation was a test naming/formatting mistake.
        ("w2/irs_w2_mod11.pdf", ["10535", "SETH W. WIGGINS"]),
        ("w2/irs_w2_2012.pdf", ["17,253.00", "BRANDON R. COOPER"]),
        ("1099/irs_1099nec_ellis.pdf", ["Nancy Ellis", "15,250"]),
        ("1099/irs_1099int_mod3.pdf", ["TASHA MILLER", "43"]),
    ],
)
def test_fillable_values_and_page_image_reach_the_model_input(
    acceptance_source_docs, local_pdf_tools, relative_path, needles
):
    preprocess = resolve_callable(names.PREPROCESS_FILE)
    document = preprocess(acceptance_source_docs / relative_path)
    normal = document.extracted_text.replace("\r", "").replace("\n", " ")
    for needle in needles:
        assert needle.replace("\r", " ") in normal
    assert len(document.page_images_b64) == document.total_pages
    assert all(document.page_images_b64)
    if relative_path.endswith("irs_w2_mod11.pdf"):
        print("irs_w2_mod11 widget values:", document.widget_values)
        print("irs_w2_mod11 model-input text:", document.extracted_text)


@pytest.mark.parametrize(
    "relative_path,description",
    [
        ("credit_card/flowparse_card_us.pdf", "COPPER KETTLE BISTRO"),
        ("bank_statement/flowparse_bank_us.pdf", "ACH DEBIT \u2014 BLUE RIVER WHOLESALE INV 8841"),
    ],
)
def test_watermark_letters_do_not_enter_transaction_lines(
    acceptance_source_docs, relative_path, description
):
    preprocess = resolve_callable(names.PREPROCESS_FILE)
    document = preprocess(acceptance_source_docs / relative_path)
    lines = [
        " ".join(str(word.get("text", "")) for word in line)
        for page in document.page_lines
        for line in page
    ]
    matches = [line for line in lines if description in line]
    assert matches, f"transaction line not found: {description}"
    for line in matches:
        assert not re.search(r"(?:^|\s)[SAMPLE](?:\s|$)", line), line


@pytest.mark.parametrize(
    "relative_path",
    [
        "scans_made/scan_irs_1099nec_ellis.pdf",
        "scans_made/scan_utep_paystub.pdf",
        "receipt_photo/shell_mastercard.jpg",
        "receipt_photo/calif_restaurant_2006.jpg",
        "payslip/utep_paystub.pdf",
        "payslip/isu_paycheck.pdf",
    ],
)
def test_scans_photos_and_payslips_produce_geometric_words_and_images(
    acceptance_source_docs, local_pdf_tools, relative_path
):
    preprocess = resolve_callable(names.PREPROCESS_FILE)
    document = preprocess(acceptance_source_docs / relative_path)
    geometric_words = [word for page in document.page_lines for line in page for word in line]
    assert geometric_words, relative_path
    for word in geometric_words[:25]:
        assert word.get("text")
        assert all(key in word for key in ("x0", "x1", "top", "bottom", "page"))
    assert len(document.page_images_b64) == document.total_pages
    assert len(document.page_origins) == document.total_pages


def _three_rows_answer():
    rows = []
    for date, description, amount in (
        ("09/02/2026", "ACH DEBIT", "254.00"),
        ("09/03/2026", "RENT PAYMENT", "488.56"),
        ("09/04/2026", "CHECK", "85.00"),
    ):
        rows.append({
            "cells": {"Date": date, "Description": description, "Amount": amount},
            "source": f"{date} {description} {amount}", "page": 1,
        })
    return {"tables": {"table": rows}}


@pytest.mark.parametrize("failure", ["ocr_failed", "ocr_zero"])
def test_failed_or_zero_word_ocr_page_is_attention_with_reason(failure):
    page = [
        ("DATE", "DESCRIPTION", "AMOUNT"),
        ("09/02/2026", "ACH DEBIT", "254.00"),
        ("09/03/2026", "RENT PAYMENT", "488.56"),
        ("09/04/2026", "CHECK", "85.00"),
    ]
    data = run_synthetic(
        lambda **_kwargs: model_response(_three_rows_answer()),
        [page, []],
        origins={1: "native", 2: "ocr"},
        unreadable={failure: [2]},
    )
    assert_non_ready_with_reason(data)
    assert page_ledger_of(data) == {"1": names.PAGE_STATE_PROCESSED,
                                    "2": names.PAGE_STATE_FAILED}


def test_one_failed_page_does_not_discard_other_pages(monkeypatch):
    import llm_contract as contract

    monkeypatch.setattr(
        contract, "setting",
        lambda key, default: {"PAGE_CALL_MIN_PAGES": 6, "PAGE_CALL_CONCURRENCY": 2}.get(
            key, default
        ),
    )
    statement_pages = [
        ["DATE DESCRIPTION AMOUNT", f"09/0{page}/2026 ITEM-{page}A 1{page}.00",
         f"09/0{page}/2026 ITEM-{page}B 2{page}.00"]
        for page in (1, 2, 3)
    ]
    other_pages = [["Vendor list", "ACME SUPPLY", "BETA LLC"] for _ in range(4)]
    calls = []

    def extract(**kwargs):
        match = re.search(r"This is page (\d+) of", kwargs["prompt"])
        page = int(match.group(1)) if match else 0
        calls.append(page)
        if page == 2:
            return model_response(None, error_kind="invalid_json")
        rows = [{
            "cells": {"Date": f"09/0{page}/2026", "Description": f"ITEM-{page}",
                      "Amount": f"1{page}.00"},
            "source": f"09/0{page}/2026 ITEM-{page} 1{page}.00", "page": 1,
        }]
        return model_response({"tables": {"table": rows}})

    data = run_synthetic(extract, statement_pages + other_pages)
    assert page_ledger_of(data)["2"] == names.PAGE_STATE_FAILED
    assert {row["_page"] for row in data["table_rows"]} == {1, 3}
    assert calls.count(2) >= 2
    assert_non_ready_with_reason(data)


def test_heavy_file_has_explicit_page_states_and_skips_non_band_pages(monkeypatch):
    import llm_contract as contract

    monkeypatch.setattr(
        contract, "setting",
        lambda key, default: {"PAGE_CALL_MIN_PAGES": 6, "PAGE_CALL_CONCURRENCY": 2}.get(
            key, default
        ),
    )
    pages = [
        ["DATE DESCRIPTION AMOUNT", f"01/0{page}/2026 ITEM-{page} {page}0.00"]
        for page in (1, 2)
    ] + [[f"Narrative page {page}", "No matching table"] for page in range(3, 27)]
    calls = []

    def extract(**kwargs):
        match = re.search(r"This is page (\d+) of", kwargs["prompt"])
        page = int(match.group(1)) if match else 0
        calls.append(page)
        return model_response({"tables": {"table": [{
            "cells": {"Date": f"01/0{page}/2026", "Description": f"ITEM-{page}",
                      "Amount": f"{page}0.00"},
            "source": f"01/0{page}/2026 ITEM-{page} {page}0.00", "page": 1,
        }]}})

    data = run_synthetic(extract, pages)
    ledger = page_ledger_of(data)
    assert len(ledger) == 26
    assert set(ledger.values()) <= {
        names.PAGE_STATE_PROCESSED,
        names.PAGE_STATE_PROCESSED_EMPTY,
        names.PAGE_STATE_FAILED,
    }
    assert calls == [1, 2]
    assert len(data["table_rows"]) == 2
    assert state_of(data) != names.DOCUMENT_STATE_FAILED


@pytest.mark.xfail(
    strict=True,
    reason=("A8.3 real app gap: no check compares extracted row sums with a "
            "printed table total"),
)
def test_A8_3_row_sum_versus_printed_total_is_not_built():
    import source_inventory as inventory

    page_lines = [words(1, [
        "DATE DESCRIPTION AMOUNT",
        "01/01 ITEM-A 40.00",
        "01/02 ITEM-B 60.00",
        "Printed total 110.00",
    ])]
    slots = {"fields": [], "tables": [{"name": "table", "columns": [
        {"header": "Date"}, {"header": "Description"}, {"header": "Amount"},
    ]}]}
    rows = {"table": [
        {"Date": "01/01", "Description": "ITEM-A", "Amount": "40.00"},
        {"Date": "01/02", "Description": "ITEM-B", "Amount": "60.00"},
    ]}
    coverage = inventory.coverage(
        inventory.build(page_lines, [1]), slots, {}, rows, {}, page_lines, [1]
    )
    assert any("row_sum_mismatch" in reason for reason in coverage[names.REASONS_FIELD])


def test_five_amount_scan_rule_adds_zero_calls_on_26_page_fixture(
    acceptance_source_docs, local_pdf_tools
):
    import source_inventory as inventory

    preprocess = resolve_callable(names.PREPROCESS_FILE)
    document = preprocess(acceptance_source_docs / "long_docs/long_digital_25pg.pdf")
    page_numbers = list(range(1, document.total_pages + 1))
    origins = {index + 1: origin for index, origin in enumerate(document.page_origins)}
    source = inventory.build(
        document.page_lines, page_numbers, document.widget_values, origins
    )
    ocr_amounts = {
        page: len(source["pages"][page]["amounts"])
        for page in page_numbers
        if origins[page] in {"ocr", "pre_ocr"}
    }
    extra_calls = [page for page, count in ocr_amounts.items() if count >= 5]
    print(
        f"26-page fixture: OCR pages={ocr_amounts}; "
        f"5+ amount rule extra page calls={len(extra_calls)} ({extra_calls})"
    )
    assert document.total_pages == 26
    assert ocr_amounts == {22: 1, 23: 0}
    assert extra_calls == []
