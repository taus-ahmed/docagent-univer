"""Run T1, 1b: a job's cost is priced per model, input and output apart,
over every attempt (retries, sized pieces, thinking, options)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import llm_contract as C  # noqa: E402


def _a(model, inp, out, think=0):
    return {"model_requested": model, "model_version": model,
            "prompt_tokens": inp, "output_tokens": out, "thinking_tokens": think}


class TestBreakdown:
    def test_input_and_output_priced_apart(self):
        # gemini-2.5-flash: $0.30 in / $2.50 out per 1M
        b = C.cost_breakdown([_a("gemini-2.5-flash", 100_000, 10_000)])
        assert b["usd"] == round(0.1 * 0.30 + 0.01 * 2.50, 6) == 0.055

    def test_the_blended_rate_undercounted_this_call(self):
        # 20,000 in + 21,334 out on 2.5-flash: the job summary said $0.0062
        # (41,334 x $0.15/M); the call is worth ~$0.0593
        b = C.cost_breakdown([_a("gemini-2.5-flash", 20_000, 21_334)])
        assert abs(b["usd"] - (0.02 * 0.30 + 0.021334 * 2.50)) < 1e-9
        assert b["usd"] > 9 * (41_334 / 1e6 * 0.15)

    def test_thinking_is_billed_as_output(self):
        b = C.cost_breakdown([_a("gemini-2.5-flash-lite", 0, 1000, 4000)])
        assert b["usd"] == round(5000 / 1e6 * 0.40, 6)
        assert b["thinking_tokens"] == 4000

    def test_retries_and_pieces_all_count(self):
        att = [_a("gemini-2.5-flash", 1000, 0), _a("gemini-2.5-flash", 1000, 500),
               _a("gemini-2.5-flash", 1000, 500)]
        b = C.cost_breakdown(att)
        assert b["calls"] == 3 and b["input_tokens"] == 3000
        assert b["usd"] == round(3000 / 1e6 * 0.30 + 1000 / 1e6 * 2.50, 6)

    def test_models_priced_separately(self):
        b = C.cost_breakdown([_a("gemini-2.5-flash", 1_000_000, 0),
                              _a("gemini-2.5-flash-lite", 1_000_000, 0)])
        assert b["by_model"]["gemini-2.5-flash"]["usd"] == 0.30
        assert b["by_model"]["gemini-2.5-flash-lite"]["usd"] == 0.10
        assert b["usd"] == 0.40

    def test_unpriced_model_is_counted_not_guessed(self):
        b = C.cost_breakdown([_a("someone-else-1", 1000, 1000)])
        assert b["usd"] == 0 and b["unpriced_calls"] == 1
        assert "unpriced" in C.cost_line(b)

    def test_refused_call_costs_nothing(self):
        b = C.cost_breakdown([{"model_requested": "gemini-2.5-flash",
                               "prompt_tokens": None, "output_tokens": None}])
        assert b["usd"] == 0 and b["calls"] == 1 and b["unpriced_calls"] == 0

    def test_one_table_overrides(self, monkeypatch):
        monkeypatch.setattr(C, "setting", lambda k, d=None: (
            '{"gemini-2.5-flash": {"input": 1.0, "output": 2.0}}'
            if k == "LLM_PRICE_TABLE" else d))
        b = C.cost_breakdown([_a("gemini-2.5-flash", 1_000_000, 1_000_000)])
        assert b["usd"] == 3.0


class TestDocCost:
    def test_document_cost_includes_options_and_extraction(self):
        from app.services.job_worker import doc_cost_of
        ed = {"diagnostics": {
            "attempts": [_a("gemini-2.5-flash", 100_000, 10_000)],
            "option_attempts": [_a("gemini-2.5-flash", 10_000, 1_000)]}}
        b = doc_cost_of(ed, None, 999)
        assert b["basis"] == "per-model rates"
        assert b["usd"] == round(0.055 + 0.01 * 0.30 + 0.001 * 2.50, 6)

    def test_no_counters_falls_back_and_says_so(self):
        from app.services.job_worker import doc_cost_of
        b = doc_cost_of({}, SimpleNamespace(extraction_response=None), 1_000_000)
        assert b["usd"] == 0.15 and "blended" in b["basis"]

    def test_merge(self):
        from app.services.job_worker import _merge_cost, doc_cost_of
        tot = {"usd": 0.0, "by_model": {}}
        for _ in range(2):
            _merge_cost(tot, doc_cost_of(
                {"diagnostics": {"attempts": [_a("gemini-2.5-flash", 100_000, 10_000)]}},
                None, 0))
        assert tot["usd"] == 0.11 and tot["by_model"]["gemini-2.5-flash"]["calls"] == 2
