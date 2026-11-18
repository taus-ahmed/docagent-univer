from __future__ import annotations

import json

import pytest

from tests.contract import names
from tests.contract.adapter import assert_non_ready_with_reason, evaluate_answer, state_of


RUN_A2 = pytest.mark.xfail(
    strict=True,
    reason="Run A2: typed answer-contract failures and section retries are not implemented",
)


def _record(path, number):
    return json.loads((path / f"job{number}.json").read_text(encoding="utf-8"))[0]


def _raw(record):
    return record["extracted_data"]["raw_llm_responses"][0]


@pytest.mark.parametrize(
    "case,record_number,raw,finish_reason,candidates",
    [
        pytest.param("missing_tables", 15, None, "STOP", 1, id="real-job15-missing-tables"),
        pytest.param("mostly_empty", 21, None, "STOP", 1, id="real-job21-empty-slots"),
        pytest.param("label_only_sources", 25, None, "STOP", 1, id="real-job25-label-sources"),
        pytest.param("empty_object", None, "{}", "STOP", 1, id="empty-object"),
        pytest.param("whitespace", None, "  \n\t", "STOP", 1, id="whitespace"),
        pytest.param("invalid_json", None, "{not json", "STOP", 1, id="invalid-json"),
        pytest.param("no_candidates", None, "", "STOP", 0, id="no-candidates"),
        pytest.param("blocked", None, "", "SAFETY", 1, id="blocked"),
        pytest.param("max_tokens", None, "{\"fields\": {", "MAX_TOKENS", 1, id="max-tokens"),
    ],
)
@RUN_A2
def test_incomplete_or_unusable_answers_never_become_ready(
    acceptance_job_records, case, record_number, raw, finish_reason, candidates
):
    if record_number is not None:
        raw = _raw(_record(acceptance_job_records, record_number))
    result = evaluate_answer(
        model_result={
            "raw_text": raw,
            "finish_reason": finish_reason,
            "candidates": [{}] * candidates,
        },
        expected_slots=["F1", "F2", "F3"],
        expected_tables=["table"],
        section=case,
    )
    assert_non_ready_with_reason(result)


@RUN_A2
def test_max_tokens_can_request_a_retry_without_claiming_ready():
    result = evaluate_answer(
        model_result={"raw_text": "", "finish_reason": "MAX_TOKENS", "candidates": [{}]},
        expected_slots=["F1"],
        expected_tables=[],
        section="header",
    )
    assert state_of(result) != names.DOCUMENT_STATE_READY
    assert result.get("retry") or result.get(names.DIAGNOSTICS_FIELD)


@RUN_A2
def test_job19_healthy_po_round_trips_without_new_flags(acceptance_job_records):
    record = _record(acceptance_job_records, 19)
    raw = _raw(record)
    result = evaluate_answer(
        model_result={"raw_text": raw, "finish_reason": "STOP", "candidates": [{}]},
        expected_slots=[f"F{i}" for i in range(1, 14)],
        expected_tables=["table"],
        section="full_document",
    )
    assert state_of(result) == names.DOCUMENT_STATE_READY
    assert result["answer"] == json.loads(raw)
    assert not result.get(names.DIAGNOSTICS_FIELD, {}).get(names.REASONS_FIELD)


def test_recorded_job19_is_an_unchanged_healthy_control(acceptance_job_records):
    record = _record(acceptance_job_records, 19)
    data = record["extracted_data"]
    assert data["extracted_fields"] == {
        "B1": "PO-2026-1147",
        "B2": "2026-10-05",
        "B3": "2026-10-19",
        "B4": "Harlow & Sons Ltd",
        "B5": "Ormond Storage Systems Ltd",
        "B9": "30 days from invoice",
        "B33": "£4,356.80",
        "B34": "£871.36",
        "B35": "£5,228.16",
    }
    assert len(data["table_rows"]) == 5
    assert data["validation"]["low_confidence_cells"] == 0
    assert data["validation"]["document_needs_review"] is False
