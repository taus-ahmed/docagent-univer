from __future__ import annotations

import re

import pytest

from tests.contract import names
from tests.contract.adapter import assert_non_ready_with_reason, evaluate_answer, resolve_callable


RUN_A3 = pytest.mark.xfail(
    strict=True,
    reason="Run A3: page ledger, OCR failure states, and image/input evidence contract are not implemented",
)
RUN_A4 = pytest.mark.xfail(
    strict=True,
    reason="Run A4: per-page completeness and continued-band reconciliation are not implemented",
)


@pytest.mark.parametrize(
    "relative_path,needles",
    [
        ("w2/irs_w2_mod11.pdf", ["10,535", "SETH W. WIGGINS"]),
        ("w2/irs_w2_2012.pdf", ["17,253.00", "BRANDON R. COOPER"]),
        ("1099/irs_1099nec_ellis.pdf", ["Nancy Ellis", "15,250"]),
        ("1099/irs_1099int_mod3.pdf", ["TASHA MILLER", "43"]),
    ],
)
@RUN_A3
def test_fillable_values_and_page_image_reach_the_model_input(
    acceptance_source_docs, relative_path, needles
):
    preprocess = resolve_callable(names.PREPROCESS_FILE)
    document = preprocess(acceptance_source_docs / relative_path)
    normal = document.extracted_text.replace("\r", "").replace("\n", " ")
    for needle in needles:
        assert needle.replace("\r", " ") in normal
    assert len(document.page_images_b64) == document.total_pages
    assert all(document.page_images_b64)


@pytest.mark.parametrize(
    "relative_path,description",
    [
        ("credit_card/flowparse_card_us.pdf", "COPPER KETTLE BISTRO"),
        ("bank_statement/flowparse_bank_us.pdf", "ACH DEBIT — BLUE RIVER WHOLESALE INV 8841"),
    ],
)
def test_watermark_letters_do_not_enter_transaction_lines(
    acceptance_source_docs, relative_path, description
):
    preprocess = resolve_callable(names.PREPROCESS_FILE)
    document = preprocess(acceptance_source_docs / relative_path)
    lines = [" ".join(str(w.get("text", "")) for w in line) for page in document.page_lines for line in page]
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
    acceptance_source_docs, relative_path
):
    preprocess = resolve_callable(names.PREPROCESS_FILE)
    document = preprocess(acceptance_source_docs / relative_path)
    words = [word for page in document.page_lines for line in page for word in line]
    assert words, relative_path
    for word in words[:25]:
        assert word.get("text")
        assert all(key in word for key in ("x0", "x1", "top", "bottom", "page"))
    assert len(document.page_images_b64) == document.total_pages
    assert len(document.page_origins) == document.total_pages


@pytest.mark.parametrize("failure", ["ocr_failed", "ocr_zero_words"])
@RUN_A3
def test_failed_or_zero_word_ocr_page_is_attention_with_reason(failure):
    result = evaluate_answer(
        model_result={"raw_text": "{}", "finish_reason": "STOP", "candidates": [{}]},
        expected_slots=["F1"],
        expected_tables=[],
        section="page_2",
        source_inventory={
            "pages": [
                {"page": 1, "origin": "ocr", "words": 15},
                {"page": 2, "origin": "ocr", "words": 0, "failure": failure},
            ]
        },
    )
    assert_non_ready_with_reason(result)
    ledger = result[names.COVERAGE_FIELD][names.PAGE_LEDGER_FIELD]
    assert ledger["processed"] == 2 and ledger["total"] == 2
    assert ledger["pages"][1][names.PAGE_STATE_FIELD] in {"NEEDS_ATTENTION", "FAILED"}


@RUN_A3
def test_one_failed_page_does_not_discard_other_pages():
    result = evaluate_answer(
        model_result={
            "per_page_answers": [
                {"page": 1, "fields": {"F1": {"value": "kept"}}},
                {"page": 2, "error": "ocr_failed"},
                {"page": 3, "fields": {"F2": {"value": "also kept"}}},
            ]
        },
        expected_slots=["F1", "F2"],
        expected_tables=[],
        section="full_document",
        source_inventory={"page_count": 3},
    )
    assert result["answer"]["fields"]["F1"]["value"] == "kept"
    assert result["answer"]["fields"]["F2"]["value"] == "also kept"
    assert_non_ready_with_reason(result)


@RUN_A4
def test_heavy_file_has_explicit_page_states_and_continuation_rules():
    per_page = [
        {"page": page, "fields": {}, "tables": {}, "note": "no matching table"}
        for page in range(1, 27)
    ]
    per_page[0]["tables"] = {"Transactions": [{"Date": "01/01", "Amount": 40.0}]}
    per_page[1]["tables"] = {"Transactions": [{"Date": "01/02", "Amount": 60.0}]}
    result = evaluate_answer(
        model_result={"per_page_answers": per_page},
        expected_slots=[],
        expected_tables=["Transactions"],
        section="full_document",
        source_inventory={"page_count": 26, "printed_band_total": 110.0},
    )
    ledger = result[names.COVERAGE_FIELD][names.PAGE_LEDGER_FIELD]
    assert len(ledger["pages"]) == 26
    assert all(page[names.PAGE_STATE_FIELD] for page in ledger["pages"])
    assert len(result["answer"]["tables"]["Transactions"]) == 2
    assert all(not page.get("rows") and page.get("note") for page in ledger["pages"][2:])
    assert any(reason[names.REASON_CODE_FIELD] == "row_sum_mismatch"
               for reason in result[names.DIAGNOSTICS_FIELD][names.REASONS_FIELD])
    assert result[names.DOCUMENT_STATE_FIELD] != names.DOCUMENT_STATE_FAILED
