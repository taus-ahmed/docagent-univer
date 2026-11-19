from __future__ import annotations

import json

import pytest

from tests.contract import names
from tests.contract.adapter import assert_non_ready_with_reason, state_of


@pytest.mark.parametrize("job", [15, 21, 25])
def test_frozen_incomplete_answers_replay_as_visible_non_ready_results(replayed_jobs, job):
    replay = replayed_jobs[job]
    assert replay["calls"][0]
    assert replay["raw"] == replay["record"]["extracted_data"]["raw_llm_responses"][0]
    assert_non_ready_with_reason(replay["extracted_data"])


@pytest.mark.parametrize(
    "raw,finish,candidates,block,expected",
    [
        ("{}", "STOP", 1, None, names.FAILURE_EMPTY),
        ("  \n\t", "STOP", 1, None, names.FAILURE_EMPTY),
        ("{not json", "STOP", 1, None, names.FAILURE_INVALID_JSON),
        ("", "STOP", 0, None, names.FAILURE_NO_CANDIDATE),
        ("", "SAFETY", 1, "SAFETY", names.FAILURE_BLOCKED),
        ('{"fields": {', "MAX_TOKENS", 1, None, names.FAILURE_MAX_TOKENS),
    ],
    ids=["empty-object", "whitespace", "invalid-json", "no-candidate", "blocked", "max-tokens"],
)
def test_provider_treats_unusable_answers_as_typed_failures(
    monkeypatch, raw, finish, candidates, block, expected
):
    """The real provider parser is exercised with its HTTP seam scripted."""
    from connectors.gemini_client import GeminiClient

    client = GeminiClient(api_key="offline-test-placeholder")
    info = {
        "http_status": 200,
        "model_version": "offline-model",
        "candidate_count": candidates,
        "prompt_tokens": 10,
        "output_tokens": 2,
        "thinking_tokens": None,
        "finish_reason": finish,
        "block_reason": block,
    }
    monkeypatch.setattr(client, "_post", lambda *_args: (raw, info))
    response = client.extract_data("local document", "local prompt")
    assert response.success is False
    assert response.error_kind == expected
    assert response.parsed_json is None


def test_missing_tables_get_one_targeted_second_call_then_need_attention(replayed_jobs):
    replay = replayed_jobs[15]
    data = replay["extracted_data"]
    assert len(replay["calls"]) == 2
    assert "SECOND REQUEST" in replay["calls"][1]["prompt"]
    assert data[names.DIAGNOSTICS_FIELD][names.CONTRACT_FIELD]["retried_tables"] == ["table"]
    assert state_of(data) == names.DOCUMENT_STATE_NEEDS_ATTENTION
    assert state_of(data) != names.DOCUMENT_STATE_READY


def test_job19_healthy_po_stays_ready_and_reports_known_false_flag(replayed_jobs):
    replay = replayed_jobs[19]
    recorded = replay["record"]["extracted_data"]
    data = replay["extracted_data"]
    assert len(replay["calls"]) == 1
    assert state_of(data) == names.DOCUMENT_STATE_READY
    assert data[names.ATTENTION_FIELD] == []
    assert data["extracted_fields"] == recorded["extracted_fields"]

    strip_metadata = lambda rows: [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in rows
    ]
    assert strip_metadata(data["table_rows"]) == strip_metadata(recorded["table_rows"])

    flags = data["validation"]["flagged_fields"]
    template_columns = [flag for flag in flags if flag.get("ref") == "template columns"]
    print(f"job19 state={state_of(data)} template-columns false flags={len(template_columns)}")
    assert len(template_columns) == 1
    assert "headings do not appear" in template_columns[0]["reason"]


def test_recorded_job19_is_an_unchanged_healthy_control(acceptance_job_records):
    record = json.loads((acceptance_job_records / "job19.json").read_text(encoding="utf-8"))[0]
    data = record["extracted_data"]
    assert data["extracted_fields"] == {
        "B1": "PO-2026-1147",
        "B2": "2026-10-05",
        "B3": "2026-10-19",
        "B4": "Harlow & Sons Ltd",
        "B5": "Ormond Storage Systems Ltd",
        "B9": "30 days from invoice",
        "B33": "\u00a34,356.80",
        "B34": "\u00a3871.36",
        "B35": "\u00a35,228.16",
    }
    assert len(data["table_rows"]) == 5
    assert data["validation"]["low_confidence_cells"] == 0
    assert data["validation"]["document_needs_review"] is False
