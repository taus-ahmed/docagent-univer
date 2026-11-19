from __future__ import annotations

import contextlib
import io
from types import SimpleNamespace

import pytest


def _ok(text='{"fields": {}}', finish="STOP"):
    return text, {
        "http_status": 200,
        "model_version": "offline-model",
        "candidate_count": 1,
        "prompt_tokens": 10,
        "output_tokens": 2,
        "thinking_tokens": None,
        "finish_reason": finish,
        "block_reason": None,
    }


class ScriptedGemini:
    def __init__(self, outcomes):
        from connectors.gemini_client import GeminiClient

        self.client = GeminiClient(api_key="offline-test-placeholder")
        self.outcomes = list(outcomes)
        self.calls = []

        def post(model, body, timeout):
            self.calls.append((model, body, timeout))
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        self.client._post = post


@pytest.mark.parametrize("status", [429, 503])
def test_transient_http_failures_retry_with_bounded_backoff(monkeypatch, status):
    import llm_contract as contract
    import connectors.gemini_client as gemini_module

    delays = []
    monkeypatch.setattr(gemini_module.time, "sleep", delays.append)
    failure = contract.LLMCallError(
        contract.TRANSIENT, f"HTTP {status}", status=status,
        retry_after=2.0 if status == 429 else None,
    )
    gemini = ScriptedGemini([failure, _ok()])
    response = gemini.client.extract_data("local document", "local prompt")
    assert response.success is True
    assert len(gemini.calls) == 2
    assert len(delays) == 1
    assert 0 <= delays[0] <= 30
    if status == 429:
        assert delays[0] >= 2.0


def test_invalid_request_is_not_retried(monkeypatch):
    import llm_contract as contract
    import connectors.gemini_client as gemini_module

    delays = []
    monkeypatch.setattr(gemini_module.time, "sleep", delays.append)
    gemini = ScriptedGemini([
        contract.LLMCallError(contract.INVALID_REQUEST, "HTTP 400", status=400),
        _ok(),
    ])
    response = gemini.client.extract_data("local document", "local prompt")
    assert response.success is False
    assert response.error_kind == contract.INVALID_REQUEST
    assert len(gemini.calls) == 1
    assert delays == []


def test_corrupt_pdf_fails_before_any_model_attempt(tmp_path):
    import extractor

    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\n garbage \x00\x01 not a pdf")

    class CountingModel:
        def __init__(self):
            self.calls = 0

        def extract(self, **_kwargs):
            self.calls += 1
            raise AssertionError("a corrupt PDF must not reach the model")

    model = CountingModel()
    template = {
        "layout": {
            "cells": {"0,0": {"value": "Field"}, "0,1": {"value": ""}},
            "merges": {}, "colWidths": [], "repeatRows": [],
        },
        "doc_type": "other",
        "mode": "layout",
    }
    with contextlib.redirect_stdout(io.StringIO()):
        results = extractor.run_extraction(SimpleNamespace(llm=model), corrupt, template)
    assert len(results) == 1
    assert results[0].success is False
    assert "could not be read" in results[0].error
    assert model.calls == 0


def test_max_tokens_retries_only_the_truncated_section_once():
    import llm_contract as contract
    from connectors.base import LLMResponse
    from extractor import _llm_json

    sections = []
    calls = []

    def extract(**kwargs):
        calls.append(kwargs)
        sections.append(contract.CALL_SECTION.get())
        if len(calls) == 1:
            return LLMResponse(raw_text="", success=False, error_kind=contract.MAX_TOKENS)
        return LLMResponse(
            raw_text='{"tables": {"transactions": []}}',
            parsed_json={"tables": {"transactions": []}},
            success=True,
        )

    with contract.section("transactions"):
        parsed, _response = _llm_json(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)),
            "transaction prompt", "system", text="local text", max_output_tokens=8000,
        )
    assert parsed == {"tables": {"transactions": []}}
    assert sections == ["transactions", "transactions|retry:max_tokens"]
    assert calls[1]["max_output_tokens"] == 16000
    assert calls[1]["thinking_budget"] == 0


def test_total_transient_attempts_are_capped_at_three(monkeypatch):
    import llm_contract as contract
    import connectors.gemini_client as gemini_module

    monkeypatch.setattr(gemini_module.time, "sleep", lambda _delay: None)
    failure = contract.LLMCallError(contract.TRANSIENT, "HTTP 503", status=503)
    gemini = ScriptedGemini([failure, failure, failure, _ok()])
    response = gemini.client.extract_data("local document", "local prompt")
    assert response.success is False
    assert response.error_kind == contract.TRANSIENT
    assert len(gemini.calls) == 3


def test_partial_answer_is_never_zero_filled():
    import llm_contract as contract

    slots = {
        "fields": [{"slot_id": "F1", "ref": "B1", "row_label": "Header"}],
        "tables": [{"name": "table", "columns": [{"header": "Amount"}]}],
    }
    partial = {"fields": {"F1": {"value": "kept"}}}
    failures = contract.check_answer(partial, slots)
    assert [failure["kind"] for failure in failures] == [contract.MISSING_TABLE]
    assert partial["fields"]["F1"]["value"] == "kept"
    assert "tables" not in partial
    assert 0 not in partial["fields"].values()
