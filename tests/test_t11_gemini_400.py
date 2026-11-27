"""Run T, 11 — a Gemini HTTP 400 says WHY, and the shapes that draw one are
avoided.

The router logged "Extraction gemini failed (provider error, 30 chars, not
logged)": no status, no code, no cause. Every refusal in the stored jobs
(local_docs/raw, 11 of 11) was a response schema of 31-50 field slots; every
accepted schema held at most 26. Mocked at urllib, so the client's own HTTP
error path runs; no network.
"""
from __future__ import annotations

import io
import json
import logging
import urllib.error

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import llm_contract as C  # noqa: E402
from connectors import gemini_client as G  # noqa: E402
from connectors import llm_router  # noqa: E402

SECRET_TEXT = "Invoice for ACME-TOPSECRET customer 4111111111111111"


def _http_400(message="Invalid JSON payload: response_schema too many states",
              status="INVALID_ARGUMENT", reason=None):
    err = {"error": {"code": 400, "message": message, "status": status}}
    if reason:
        err["error"]["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                    "reason": reason}]
    body = json.dumps(err).encode()
    return urllib.error.HTTPError("https://x/v1beta/models/m:generateContent?key=K",
                                  400, "Bad Request", {}, io.BytesIO(body))


class _Ok:
    status = 200

    def __init__(self, text='{"fields": {}}'):
        self._b = json.dumps({"candidates": [{"content": {"parts": [{"text": text}]},
                                              "finishReason": "STOP"}],
                              "usageMetadata": {"promptTokenCount": 10,
                                                "candidatesTokenCount": 5},
                              "modelVersion": "gemini-test"}).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _client(monkeypatch, script):
    """A client whose HTTP calls follow `script`: each item an exception to
    raise or a response to return. Records each request body."""
    calls = []

    def urlopen(req, timeout=None):
        calls.append(json.loads(req.data.decode()))
        step = script[min(len(calls) - 1, len(script) - 1)]
        if isinstance(step, Exception):
            raise step
        return step

    monkeypatch.setattr(G.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    cl = G.GeminiClient(api_key="K")
    monkeypatch.setattr(cl, "fallbacks", lambda: [])
    cl._preferred = "gemini-test"
    return cl, calls


def _schema(n_fields, n_cols=3):
    slots = {"fields": [{"slot_id": f"F{i}"} for i in range(1, n_fields + 1)],
             "tables": [{"name": "rows"}]}
    return C.response_schema(slots, lambda t: [f"c{i}" for i in range(n_cols)])


class TestErrorBody:
    def test_status_reason_and_cause_are_read_message_is_not_kept(self):
        raw = json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                    "message": f"bad response_schema near '{SECRET_TEXT}'",
                                    "details": [{"reason": "SCHEMA_TOO_COMPLEX"}]}}).encode()
        st, rs, cause = G.api_error(raw)
        assert (st, rs, cause) == ("INVALID_ARGUMENT", "SCHEMA_TOO_COMPLEX", "schema")
        assert SECRET_TEXT not in repr((st, rs, cause))

    @pytest.mark.parametrize("msg,cause", [
        ("The input token count (1200000) exceeds the maximum", "input_too_long"),
        ("Unable to process input image", "image"),
        ("thinking_budget is not supported", "generation_config"),
        ("API key not valid", "api_key"),
        ("something else entirely", None),
    ])
    def test_causes_in_several_vocabularies(self, msg, cause):
        assert C.classify_cause(msg) == cause

    def test_garbage_body(self):
        assert G.api_error(b"<html>oops</html>") == (None, None, None)


class TestRecovery:
    def test_schema_refused_then_answered_without_it(self, monkeypatch, capsys):
        cl, calls = _client(monkeypatch, [_http_400(), _Ok()])
        r = cl.extract_data(SECRET_TEXT, "prompt", response_schema=_schema(5))
        assert r.success
        assert "responseSchema" in calls[0]["generationConfig"]
        assert "responseSchema" not in calls[1]["generationConfig"]
        bad = r.attempts[0]
        assert bad["http_status"] == 400 and bad["api_status"] == "INVALID_ARGUMENT"
        assert bad["cause"] == "schema" and bad["schema_fields"] == 5
        assert r.attempts[1]["retry_reason"] == "schema_rejected"
        out = capsys.readouterr().out
        assert "recovered" in out and "cause=schema" in out
        assert SECRET_TEXT not in out

    def test_an_oversized_schema_is_not_sent_at_all(self, monkeypatch, capsys):
        cl, calls = _client(monkeypatch, [_Ok()])
        r = cl.extract_data("doc", "prompt", response_schema=_schema(40))
        assert r.success and len(calls) == 1
        assert "responseSchema" not in calls[0]["generationConfig"]
        assert r.attempts[0]["retry_reason"] == "schema_too_large"
        assert r.attempts[0]["schema_fields"] == 40
        assert "not sent" in capsys.readouterr().out

    def test_a_schema_within_the_limit_is_still_sent(self, monkeypatch):
        cl, calls = _client(monkeypatch, [_Ok()])
        cl.extract_data("doc", "prompt", response_schema=_schema(C_LIMIT := G.SCHEMA_MAX_FIELDS))
        assert "responseSchema" in calls[0]["generationConfig"]
        assert C_LIMIT == 28


class TestNoRecovery:
    def test_router_log_names_the_cause_and_shape(self, monkeypatch, caplog, replay_cache):
        monkeypatch.setattr(llm_router.LLMRouter, "extract", replay_cache._orig["extract"])
        cl, calls = _client(monkeypatch, [_http_400("image could not be decoded")])
        router = llm_router.LLMRouter.__new__(llm_router.LLMRouter)
        router.providers = [("gemini", cl)]
        router.stats = {"failures": 0}
        with caplog.at_level(logging.WARNING):
            r = router.extract(text="", image_b64=["aGVsbG8="] * 2, prompt=SECRET_TEXT)
        assert not r.success and r.error_kind == C.INVALID_REQUEST
        line = next(m for m in caplog.messages if "Extraction gemini failed" in m)
        for part in ("http=400", "api_status=INVALID_ARGUMENT", "cause=image",
                     "model=gemini-test", "pages=2", "retried=no",
                     "fallback=none", "recovered=no"):
            assert part in line, (part, line)
        assert "not logged" not in line and SECRET_TEXT not in line
        assert len(calls) == 1                  # a 400 without a schema is not retried

    def test_the_document_carries_a_visible_reason(self, monkeypatch):
        cl, _ = _client(monkeypatch, [_http_400("API key not valid")])
        r = cl.extract_data("doc", "prompt")
        story = C.failure_story(r.attempts)
        assert "refused the request (HTTP 400: the API key was not accepted)" in story
