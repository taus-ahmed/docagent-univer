"""M1 — no silent model switch.

gemini_client walked CANDIDATES (including gemini-flash-latest and
gemini-flash-lite-latest) whenever a model answered 404, so a retired or
mistyped GEMINI_MODEL silently produced a different model's extraction.
Fallbacks are now GEMINI_MODEL_FALLBACKS (default empty) and a 404 on the
chosen model fails the call with the model named. No network: the HTTP
seam (`_post`) is replaced.
"""

from __future__ import annotations

import pytest

from tests.contract import run_a_driver as D  # noqa: F401  (bootstraps imports)

import llm_contract as C  # noqa: E402
from connectors.gemini_client import GeminiClient  # noqa: E402


def _client(monkeypatch, answers, *, fallbacks=""):
    monkeypatch.setenv("GEMINI_MODEL_FALLBACKS", fallbacks)
    cl = GeminiClient(api_key="offline-test-key")
    cl._preferred = "gemini-2.5-flash"
    seen = []

    def post(model, body, timeout):
        seen.append(model)
        a = answers.get(model)
        if a is None or isinstance(a, Exception):
            raise a or C.LLMCallError(C.MODEL_NOT_FOUND, f"404 models/{model} is not found",
                                      status=404)
        return a, {"model_version": model + "-001", "candidate_count": 1,
                   "prompt_tokens": 1, "output_tokens": 1, "thinking_tokens": 0,
                   "finish_reason": "STOP", "http_status": 200}

    monkeypatch.setattr(cl, "_post", post)
    return cl, seen


def test_the_latest_aliases_are_gone():
    assert not hasattr(GeminiClient, "CANDIDATES") or not any(
        "latest" in m for m in GeminiClient.CANDIDATES)


def test_a_404_on_the_chosen_model_fails_visibly_naming_it(monkeypatch):
    cl, seen = _client(monkeypatch, {"gemini-2.5-flash-lite": '{"ok": 1}'})
    with pytest.raises(C.LLMCallError) as e:
        cl._generate([{"text": "x"}])
    assert seen == ["gemini-2.5-flash"], "never switched to another model"
    assert e.value.kind == C.MODEL_NOT_FOUND
    assert "gemini-2.5-flash" in str(e.value)


def test_a_configured_fallback_is_used_and_recorded(monkeypatch):
    cl, seen = _client(monkeypatch, {"gemini-2.5-flash-lite": '{"ok": 1}'},
                       fallbacks="gemini-2.5-flash-lite")
    text, meta = cl._generate([{"text": "x"}])
    assert seen == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
    assert meta["model_used"] == "gemini-2.5-flash-lite"
    assert [a.get("model_requested") for a in meta["attempts"]] == seen


def test_the_extraction_response_names_the_missing_model(monkeypatch):
    cl, _seen = _client(monkeypatch, {})
    r = cl.extract_data(text="hello", prompt="p")
    assert r.success is False
    assert "gemini-2.5-flash" in (r.error or "")
