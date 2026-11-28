"""Run T3, Stage 1: GEMINI_THINKING_BUDGET_PLAN defaults to 0 for
structure-plan calls; extraction calls follow GEMINI_THINKING_BUDGET.
Applied only to gemini-2.5 models; gemini-3.x uses thinkingLevel instead.
"""
import sys
import os
import types
import pytest

# ---------------------------------------------------------------------------
# helpers to get _gen_config without a network call
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _engine_path(tmp_path):
    backend = os.path.join(os.path.dirname(__file__), "..", "backend")
    engine  = os.path.join(backend, "engine")
    for p in (backend, engine):
        if p not in sys.path:
            sys.path.insert(0, p)


def _gen_config(model, thinking_budget):
    """Call GeminiClient._gen_config with fake credentials."""
    # import after sys.path is set by the fixture
    import importlib
    import connectors.gemini_client as gc
    client = gc.GeminiClient.__new__(gc.GeminiClient)
    client.api_key = "fake"
    client._preferred = model
    client._good_model = None
    return client._gen_config(model=model, temperature=0.0,
                              max_tokens=8192, response_schema=None,
                              thinking_budget=thinking_budget,
                              force_json=False)


# ---------------------------------------------------------------------------
# Stage 1a: thinking budget sent for gemini-2.5
# ---------------------------------------------------------------------------

class TestThinkingBudgetConfig:

    def test_plan_default_budget_zero_sent_as_thinkingBudget(self):
        """GEMINI_THINKING_BUDGET_PLAN defaults to 0 → thinkingBudget=0 in
        the generation config sent to gemini-2.5-flash."""
        cfg = _gen_config("gemini-2.5-flash", thinking_budget=0)
        assert cfg.get("thinkingConfig") == {"thinkingBudget": 0}, (
            "budget=0 must be sent so the model turns thinking off")

    def test_plan_nonzero_budget_forwarded(self):
        """A non-zero plan budget is forwarded verbatim."""
        cfg = _gen_config("gemini-2.5-flash", thinking_budget=512)
        assert cfg.get("thinkingConfig") == {"thinkingBudget": 512}

    def test_no_thinking_budget_when_none(self):
        """thinking_budget=None → no thinkingConfig key (model uses its
        own default, which may include thinking tokens)."""
        cfg = _gen_config("gemini-2.5-flash", thinking_budget=None)
        # _gen_config reads the env/settings; if GEMINI_THINKING_BUDGET
        # is unset (None), no thinkingConfig is added
        # (the fixture does not set GEMINI_THINKING_BUDGET so it stays None)
        import llm_contract as C
        bgt = C.setting("GEMINI_THINKING_BUDGET", None)
        if bgt is None:
            assert "thinkingConfig" not in cfg
        else:
            assert cfg.get("thinkingConfig", {}).get("thinkingBudget") == bgt

    def test_gemini_25_flash_lite_budget_sent(self):
        cfg = _gen_config("gemini-2.5-flash-lite", thinking_budget=0)
        assert cfg.get("thinkingConfig") == {"thinkingBudget": 0}

    def test_gemini_3x_uses_level_not_budget(self):
        """gemini-3.x uses thinkingLevel, not thinkingBudget; a budget
        value must NOT appear in the config for a 3.x model."""
        for model in ("gemini-3.6-flash", "gemini-3.8-flash"):
            cfg = _gen_config(model, thinking_budget=512)
            assert "thinkingBudget" not in str(cfg), (
                f"{model} must not receive thinkingBudget (uses thinkingLevel)")
            # gemini-3.x profile sends thinkingLevel from the profile
            tc = cfg.get("thinkingConfig") or {}
            assert "thinkingLevel" in tc or tc == {}, (
                f"{model}: expected thinkingLevel or no thinkingConfig")

    def test_gemini_3x_budget_zero_does_not_override_level(self):
        """Passing budget=0 to a 3.x model must not send thinkingBudget=0."""
        cfg = _gen_config("gemini-3.8-flash", thinking_budget=0)
        assert "thinkingBudget" not in str(cfg)

    def test_plan_calls_pass_budget_zero_by_default(self, monkeypatch):
        """perception_store.plan_pages passes thinking_budget=0 (the default
        GEMINI_THINKING_BUDGET_PLAN) to _llm_json for structure-plan calls."""
        import app.services.paths  # noqa — ensure engine on sys.path
        captured = {}

        # patch _llm_json so we can inspect kwargs without a network call
        import extractor as EX
        original = EX._llm_json

        def fake_llm_json(orch, prompt, system, **kw):
            captured.update(kw)
            # return a valid (None, None) pair so ask_plan fails gracefully
            return None, None

        monkeypatch.setattr(EX, "_llm_json", fake_llm_json)

        # Build a minimal stub orchestrator
        import types
        orch = types.SimpleNamespace(llm=None)

        # Build a minimal page and perception
        import structure_engine as S
        page = {
            "page": 1, "width": 612, "height": 792,
            "lines": [{"id": "L1", "text": "Hello world", "x0": 10, "x1": 200,
                       "top": 100, "bottom": 115, "baseline": 112, "size": 12,
                       "word_ids": ["p1w1", "p1w2"]}],
            "words": [{"id": "p1w1", "text": "Hello", "x0": 10, "x1": 50,
                       "top": 100, "bottom": 115, "baseline": 112, "size": 12},
                      {"id": "p1w2", "text": "world", "x0": 55, "x1": 100,
                       "top": 100, "bottom": 115, "baseline": 112, "size": 12}],
            "edges": {"h": [], "v": []},
        }
        perc = {"pages": [page]}

        import tempfile, pathlib
        import app.services.perception_store as PS

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            fname = f.name

        try:
            PS.plan_pages(perc, orch, pathlib.Path(fname))
        except Exception:
            pass  # may fail due to fake orch — we only care about captured

        assert "thinking_budget" in captured, \
            "plan_pages must pass thinking_budget to _llm_json"
        assert captured["thinking_budget"] == 0, (
            f"plan_pages must pass thinking_budget=0 (GEMINI_THINKING_BUDGET_PLAN "
            f"default), got {captured['thinking_budget']!r}")
