"""Run T3, Stage 2: failed calls with no token data cost $0, not an
estimate based on a blended per-token rate."""
import sys
import os
import pytest


@pytest.fixture(autouse=True)
def _engine_path():
    backend = os.path.join(os.path.dirname(__file__), "..", "backend")
    engine  = os.path.join(backend, "engine")
    for p in (backend, engine):
        if p not in sys.path:
            sys.path.insert(0, p)


class TestFailedCallCostZero:
    """finish_attempt: a failed call with no tokens gets cost_estimate=0.0,
    not None. cost_breakdown counts it as a call but bills $0."""

    def _make_attempt(self, error_kind=None, prompt_tokens=None,
                      output_tokens=None, thinking_tokens=None):
        import llm_contract as C
        rec = C.new_attempt("gemini-2.5-flash", retry=0)
        rec["prompt_tokens"] = prompt_tokens
        rec["output_tokens"] = output_tokens
        rec["thinking_tokens"] = thinking_tokens
        rec["error_kind"] = error_kind
        rec["latency_ms"] = 120000
        C.finish_attempt(rec, log=False)
        return rec

    def test_timeout_no_tokens_cost_zero(self):
        """A transport timeout that returned no token counts → cost=0.0."""
        rec = self._make_attempt(error_kind="timeout")
        assert rec["cost_estimate"] == 0.0, (
            f"timed-out call with no tokens must cost exactly $0, "
            f"got {rec['cost_estimate']!r}")

    def test_transient_no_tokens_cost_zero(self):
        import llm_contract as C
        rec = self._make_attempt(error_kind=C.TRANSIENT)
        assert rec["cost_estimate"] == 0.0

    def test_max_tokens_error_with_actual_tokens_keeps_real_cost(self):
        """A MAX_TOKENS failure that DID return token counts gets a real
        cost (not forced to zero)."""
        rec = self._make_attempt(error_kind="max_tokens",
                                 prompt_tokens=10000,
                                 output_tokens=8192)
        # cost_estimate should be non-None and > 0 for a priced model
        assert rec["cost_estimate"] is not None
        assert rec["cost_estimate"] > 0

    def test_successful_call_not_affected(self):
        """A successful call (no error_kind) keeps its real cost."""
        rec = self._make_attempt(error_kind=None,
                                 prompt_tokens=5000,
                                 output_tokens=1000)
        assert rec["cost_estimate"] is not None
        assert rec["cost_estimate"] > 0

    def test_cost_breakdown_failed_call_zero(self):
        """cost_breakdown sums a failed-no-tokens attempt as $0."""
        import llm_contract as C
        failed = self._make_attempt(error_kind=C.TRANSIENT)
        b = C.cost_breakdown([failed])
        assert b["usd"] == 0.0, (
            f"failed no-token call must contribute $0 to breakdown, got ${b['usd']}")
        assert b["calls"] == 1, "failed call must still be counted"

    def test_no_tokens_no_error_still_none(self):
        """A call with no error_kind and no tokens (edge case) stays None."""
        rec = self._make_attempt(error_kind=None,
                                 prompt_tokens=None,
                                 output_tokens=None)
        # cost_estimate should be None (priced but no data)
        assert rec["cost_estimate"] is None
