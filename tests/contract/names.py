"""Run A contract names, copied from the implementation rather than guessed.

Every constant below cites the implementation line that defines or consumes
the name. The acceptance suite keeps these names in one place so a future
contract change has one explicit audit point.
"""

# Stored document state: backend/engine/slot_extractor.py:2241-2246 and
# backend/app/core/review.py:493-505.
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

# Completeness reasons are stored as plain-sentence attention items, not typed
# ``diagnostics.reasons`` entries: backend/app/core/review.py:466-490 and
# backend/engine/slot_extractor.py:2241-2242.
ATTENTION_FIELD = "attention"
ATTENTION_ID_FIELD = "id"
ATTENTION_TEXT_FIELD = "text"
DISPOSITION_FIELD = "disposition"
DISPOSITION_CHOICE_FIELD = "choice"

# Diagnostics shape: backend/engine/slot_extractor.py:2267-2277.
DIAGNOSTICS_FIELD = "diagnostics"
ATTEMPTS_FIELD = "attempts"
USAGE_FIELD = "usage"
CONTRACT_FIELD = "contract"
SOURCE_INVENTORY_FIELD = "inventory"
COVERAGE_FIELD = "coverage"
PAGE_LEDGER_FIELD = "pages"

# Coverage shape: backend/engine/source_inventory.py:322-333,472-479 and
# backend/engine/slot_extractor.py:2273-2276.
REASONS_FIELD = "reasons"
FLAG_SLOTS_FIELD = "flag_slots"
ABSENT_FIELD = "absent"
EMPTY_BANDS_FIELD = "empty_bands"
WIDGET_VALUES_FIELD = "widget_values"
UNPLACED_WIDGET_VALUES_FIELD = "widget_unplaced"
UNPLACED_AMOUNTS_FIELD = "unplaced_amounts"
UNPLACED_AMOUNT_COUNT_FIELD = "unplaced_amount_count"
ROWS_FIELD = "rows"
CANDIDATE_ROWS_FIELD = "candidates"
EXTRACTED_ROWS_FIELD = "extracted"

# Page-ledger values: backend/engine/slot_extractor.py:2258-2266.
PAGE_STATE_PROCESSED = "processed"
PAGE_STATE_PROCESSED_EMPTY = "processed_empty"
PAGE_STATE_FAILED = "failed"

# Actual implementation entry points.
# backend/engine/llm_contract.py:357,414
ANSWER_CONTRACT_EVALUATOR = "llm_contract.check_answer"
ANSWER_MERGER = "llm_contract.merge_answers"
# backend/engine/source_inventory.py:151,322
SOURCE_INVENTORY_BUILDER = "source_inventory.build"
COVERAGE_EVALUATOR = "source_inventory.coverage"
# backend/engine/slot_extractor.py:1219
SLOT_EXTRACTOR = "slot_extractor.run_slot_extraction"
# backend/engine/extractor.py:69; transport retry is in
# backend/engine/connectors/gemini_client.py:206-302.
LOGICAL_CALL_EXECUTOR = "extractor._llm_json"
# backend/app/core/review.py:493,508
DOCUMENT_STATE_EVALUATOR = "app.core.review.document_state"
REVIEW_DISPOSITION_EVALUATOR = "app.core.review.apply_dispositions"
# backend/engine/core/preprocessor.py:295 and the module path installed by
# tests/harness/bootstrap.py.
PREPROCESS_FILE = "core.preprocessor.preprocess_file"

# Review/disposition payload and route: backend/app/api/routes/review.py:159-168,
# 230. Dispositions are part of the review request; there is no separate route.
REVIEW_ROUTE = "/api/jobs/{job_id}/docs/{doc_id}/review"
DISPOSITIONS_ROUTE = REVIEW_ROUTE
DISPOSITION_CONFIRMED_ABSENT = "confirmed_absent"
DISPOSITION_ENTERED_MANUALLY = "entered_manually"

# Single-value edit routes: backend/app/api/routes/extract.py:968,986.
FIELD_EDIT_ROUTE = "/api/jobs/{job_id}/docs/{doc_id}/fields/{ref}"
CELL_EDIT_ROUTE = "/api/jobs/{job_id}/docs/{doc_id}/rows/{table}/{row}"
# Append-only edit events: backend/app/services/edits.py:178-213,251-252.
EDIT_LOG_FIELD = "edit_log"
EDIT_EVENT_KIND_FIELD = "kind"
EDIT_EVENT_OLD_FIELD = "old"
EDIT_EVENT_NEW_FIELD = "new"
# Export route and naming: backend/app/api/routes/extract.py:704-708.
DOWNLOAD_ROUTE = "/api/jobs/{job_id}/export"
DRAFT_SUFFIX = "_DRAFT"
# Legend first-line draft contract: backend/app/services/excel_cells.py:586-624.
LEGEND_SHEET = "Legend"
LEGEND_DRAFT_PREFIX = "DRAFT"

# Typed answer/transport failures: backend/engine/llm_contract.py:81-102.
FAILURE_TRANSIENT = "transient"
FAILURE_INVALID_REQUEST = "invalid_request"
FAILURE_NO_CANDIDATE = "no_candidate"
FAILURE_BLOCKED = "blocked"
FAILURE_MAX_TOKENS = "max_tokens"
FAILURE_EMPTY = "empty"
FAILURE_INVALID_JSON = "invalid_json"
FAILURE_MISSING_SLOT = "missing_slot"
FAILURE_MISSING_TABLE = "missing_table"
FAILURE_EMPTY_TABLE = "empty_table"

NON_READY_STATES = {
    DOCUMENT_STATE_NEEDS_ATTENTION,
    DOCUMENT_STATE_FAILED,
}
