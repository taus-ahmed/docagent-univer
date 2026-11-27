"""Run T2, Stage 7: tools/live_structure_check.py - offline it makes no call;
live, every call goes through a HARD $1 cap shared across runs, and each one
is logged. No real model is called here: the router is replaced."""
from __future__ import annotations

import json
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
