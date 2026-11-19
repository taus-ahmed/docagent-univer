from __future__ import annotations

import json

import pytest

from tests.contract import names
from tests.contract.adapter import assert_non_ready_with_reason, state_of


@pytest.mark.parametrize("job", [15])
def test_frozen_incomplete_answers_replay_as_visible_non_ready_results(replayed_jobs, job):
    replay = replayed_jobs[job]
    assert replay["calls"][0]
    assert replay["raw"] == replay["record"]["extracted_data"]["raw_llm_responses"][0]
    assert_non_ready_with_reason(replay["extracted_data"])


@pytest.mark.parametrize("job,truth", [(21, "irs_w2_mod11.json"),
                                       (25, "irs_1099nec_ellis.json")])
def test_frozen_empty_form_answers_are_completed_from_the_form_fields(
        replayed_jobs, golden_dir, job, truth):
    """Run B, B1. Jobs 21 and 25 were non-ready under Run A because the model
    left the form's filled values out. The PDF's own form fields now fill
    those slots (machine-read), so every golden value is correct, nothing is
    flagged and the document is READY. Job 15 (no table in the answer) is
    still non-ready above."""
    from tests.tools.score_runs import score_record

    replay = replayed_jobs[job]
    assert replay["raw"] == replay["record"]["extracted_data"]["raw_llm_responses"][0]
    data = replay["extracted_data"]
    scored = score_record(json.loads((golden_dir / truth).read_text(encoding="utf-8")),
                          {"extracted_data": data,
                           "document_state": data["document_state"]})
    assert scored["wrong"] == 0 and scored["missing"] == 0, scored["details"]
    assert scored["false_flags"] == 0
    assert state_of(data) == names.DOCUMENT_STATE_READY
    machine = [p for p in data["field_provenance"].values()
               if p.get("machine_read") == "form_field"]
    assert len(machine) >= 7


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


def test_job19_healthy_po_stays_ready_and_reports_no_false_flag(replayed_jobs):
    """Run B, B8: the "template columns" flag Run A raised here (heading
    "Item Description" against a printed "Description") was a false flag."""
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
    assert template_columns == []
    assert flags == []


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
