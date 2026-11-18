"""The only acceptance-test file that knows provisional Run A names.

Claude Code may choose different field, route, or callable names on
``fix/completeness-gate``. Update this module when that report arrives; the
acceptance tests should not be edited to chase naming differences.
"""

# Document state contract.
DOCUMENT_STATE_FIELD = "document_state"
DOCUMENT_STATE_READY = "READY"
DOCUMENT_STATE_NEEDS_REVIEW = "NEEDS_REVIEW"
DOCUMENT_STATE_NEEDS_ATTENTION = "NEEDS_ATTENTION"
DOCUMENT_STATE_FAILED = "FAILED"
DOCUMENT_STATES = {
    DOCUMENT_STATE_READY,
    DOCUMENT_STATE_NEEDS_REVIEW,
    DOCUMENT_STATE_NEEDS_ATTENTION,
    DOCUMENT_STATE_FAILED,
}

# Diagnostics and coverage contract.
DIAGNOSTICS_FIELD = "diagnostics"
REASONS_FIELD = "reasons"
REASON_CODE_FIELD = "code"
REASON_OPEN_FIELD = "open"
COVERAGE_FIELD = "coverage"
SOURCE_INVENTORY_FIELD = "source_inventory"
CANDIDATE_ROWS_FIELD = "candidate_rows"
EXTRACTED_ROWS_FIELD = "extracted_rows"
UNPLACED_AMOUNTS_FIELD = "unplaced_amounts"
UNPLACED_WIDGET_VALUES_FIELD = "unplaced_widget_values"
PAGE_LEDGER_FIELD = "page_ledger"
PAGE_STATE_FIELD = "state"

# App entry points. Each callable takes keyword arguments; the thin adapter in
# tests/contract/adapter.py makes the expected test-side shape explicit.
ANSWER_CONTRACT_EVALUATOR = (
    "app.services.completeness_gate.evaluate_answer_contract"
)
RETRY_EXECUTOR = "app.services.completeness_gate.execute_with_retries"
REVIEW_DISPOSITION_EVALUATOR = (
    "app.services.completeness_gate.apply_review_dispositions"
)
EXPORT_BUILDER = "app.api.routes.export._build_excel"
PREPROCESS_FILE = "core.preprocessor.preprocess_file"
HTTP_ACCEPTANCE_DRIVER = "tests.contract.run_a_driver.create_client"

# Review and edit routes.
REVIEW_ROUTE = "/api/review/jobs/{job_id}/docs/{doc_id}/review"
DISPOSITIONS_ROUTE = "/api/review/jobs/{job_id}/docs/{doc_id}/dispositions"
EDIT_ROUTE = "/api/jobs/{job_id}/docs/{doc_id}/edit"
DOWNLOAD_ROUTE = "/api/jobs/{job_id}/export"

# Typed reasons used by the acceptance contract. Additional codes are allowed;
# these are the minimum stable categories the UI and scorer need.
REASON_MISSING_SECTION = "missing_section"
REASON_EMPTY_ANSWER = "empty_answer"
REASON_INVALID_JSON = "invalid_json"
REASON_NO_CANDIDATES = "no_candidates"
REASON_BLOCKED = "blocked"
REASON_MAX_TOKENS = "max_tokens"
REASON_COVERAGE_GAP = "coverage_gap"
REASON_UNPLACED_VALUE = "unplaced_value"
REASON_OCR_FAILED = "ocr_failed"
REASON_EMPTY_OCR = "empty_ocr"

NON_READY_STATES = {
    DOCUMENT_STATE_NEEDS_ATTENTION,
    DOCUMENT_STATE_FAILED,
}
