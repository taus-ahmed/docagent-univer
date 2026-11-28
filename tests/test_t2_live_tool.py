"""Run T2, Stage 7: tools/live_structure_check.py - offline it makes no call;
live, every call goes through a HARD $1 cap shared across runs, and each one
is logged. No real model is called here: the router is replaced."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import live_structure_check as L  # noqa: E402


def test_offline_makes_no_call_and_prints_commands_without_a_key(capsys, monkeypatch):
    from connectors.llm_router import LLMRouter

    def boom(*a, **k):
        raise AssertionError("offline must not call the model")
    monkeypatch.setattr(LLMRouter, "extract", boom)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert L.main([]) == 0
    out = capsys.readouterr().out
    assert "offline: no calls made" in out
    assert 'Read-Host "Gemini API key" -AsSecureString' in out
    assert "Remove-Item Env:GEMINI_API_KEY" in out
    assert "--set vendor" in out and "--set expense" in out and "--set compare" in out


def test_the_named_documents_are_in_the_sets():
    assert L.VENDOR.endswith("mobile_vendor_list_8pg.pdf")
    assert L.EXPENSE_DOC == "EXP-2024-0081"
    assert len(L.COMPARE) == 20 and len(set(L.COMPARE)) == 20
    assert (ROOT / "tests" / "test_pdfs" / f"{L.EXPENSE_DOC}.pdf").exists()


def test_live_without_a_key_refuses(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert L.main(["--live"]) == 2


def _fake_router(monkeypatch, cost, model="gemini-2.5-flash-lite"):
    from connectors.base import LLMResponse
    from connectors.llm_router import LLMRouter
    calls = []

    def fake(self, **kw):
        calls.append(kw)
        return LLMResponse(raw_text="{}", parsed_json={}, model_used=model, attempts=[
            {"cost_estimate": cost, "prompt_tokens": 1000, "output_tokens": 200,
             "thinking_tokens": 0, "section": "test", "retry": 0}])
    monkeypatch.setattr(LLMRouter, "extract", fake)
    monkeypatch.setattr(LLMRouter, "classify", fake)
    return calls


def test_the_cap_refuses_before_sending_and_is_shared_across_runs(tmp_path, monkeypatch):
    from connectors.llm_router import LLMRouter
    calls = _fake_router(monkeypatch, cost=0.30)
    led = L.Ledger(tmp_path / "ledger.json", 1.00)
    L.install_cap(led, tmp_path / "calls.jsonl")
    r = LLMRouter.__new__(LLMRouter)
    for _ in range(3):
        assert LLMRouter.extract(r, prompt="x" * 400, max_output_tokens=1000).success
    assert round(led.spent, 2) == 0.90 and len(calls) == 3
    # the worst case of the next call (its whole output allowance at a dear
    # model's price) would pass $1: refused BEFORE it is sent
    refused = LLMRouter.extract(r, prompt="x" * 400, model="gemini-2.5-pro")
    assert refused.success is False and refused.error_kind == "cap" and len(calls) == 3
    # a NEW run reads the same ledger: the budget is the total, not per run
    again = L.Ledger(tmp_path / "ledger.json", 1.00)
    assert round(again.spent, 2) == 0.90 and again.refused == 1


def test_every_call_is_logged_with_tokens_cost_retries_and_chunk_size(tmp_path, monkeypatch):
    from connectors.llm_router import LLMRouter
    _fake_router(monkeypatch, cost=0.0012)
    led = L.Ledger(tmp_path / "ledger.json", 1.00)
    L.install_cap(led, tmp_path / "calls.jsonl")
    L.CONTEXT.update(set="vendor", doc="list.pdf")
    LLMRouter.extract(LLMRouter.__new__(LLMRouter), prompt="abc" * 100, image_b64=["a", "b"],
                      max_output_tokens=2048)
    rec = json.loads((tmp_path / "calls.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert rec["set"] == "vendor" and rec["doc"] == "list.pdf"
    assert rec["model_answered"] == "gemini-2.5-flash-lite"
    assert (rec["input_tokens"], rec["output_tokens"], rec["retries"]) == (1000, 200, 0)
    assert rec["cost_usd"] == 0.0012
    assert rec["chunk"]["prompt_chars"] == 300 and rec["chunk"]["images"] == 2
    assert rec["chunk"]["max_output_tokens"] == 2048
    assert "GEMINI_API_KEY" not in json.dumps(rec)


# ── the model: GEMINI_MODEL, never swapped (dry; nothing is called) ─────────

def _gemini_router(preferred):
    import connectors.gemini_client as G
    c = G.GeminiClient.__new__(G.GeminiClient)
    c._preferred = preferred
    return type("R", (), {"providers": [("gemini", c)]})()


def test_the_commands_name_the_production_model():
    text = L.commands()
    assert '$env:GEMINI_MODEL = "gemini-2.5-flash"' in text
    assert "flash-lite" not in text


def test_the_model_is_gemini_model_else_the_app_default(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert L.wanted_model() == "gemini-2.5-flash"
    monkeypatch.setenv("GEMINI_MODEL", "models/gemini-3.6-flash")
    assert L.wanted_model() == "gemini-3.6-flash"


def test_a_client_preferring_another_model_is_a_mismatch(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    assert L.model_mismatch("gemini-2.5-flash", _gemini_router("gemini-2.5-flash")) is None
    why = L.model_mismatch("gemini-2.5-flash", _gemini_router("gemini-2.5-flash-lite"))
    assert why and "gemini-2.5-flash-lite" in why
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite")
    why = L.model_mismatch("gemini-2.5-flash", _gemini_router("gemini-2.5-flash"))
    assert why and "settings.GEMINI_MODEL" in why


def test_live_refuses_before_any_call_when_the_model_was_swapped(monkeypatch, capsys):
    from app.config import settings
    from connectors.llm_router import LLMRouter

    def boom(*a, **k):
        raise AssertionError("a refused run must not call the model")
    monkeypatch.setattr(LLMRouter, "extract", boom)
    monkeypatch.setattr(LLMRouter, "classify", boom)
    for k in ("DOCAGENT_TEST_NO_DOTENV", "GEMINI_MODEL_FALLBACKS"):
        monkeypatch.setenv(k, os.environ.get(k, ""))
    monkeypatch.setenv("GEMINI_API_KEY", "dry-test-placeholder")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite")   # the swap
    monkeypatch.chdir(Path.cwd())
    assert L.main(["--live", "--set", "vendor"]) == 4
    cap = capsys.readouterr()
    assert "model: gemini-2.5-flash" in cap.out
    assert "refusing to run" in cap.err and "gemini-2.5-flash-lite" in cap.err


def test_offline_prints_the_model_it_would_use(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert L.main([]) == 0
    assert "model: gemini-2.5-flash (GEMINI_MODEL unset; the app default)" in capsys.readouterr().out
