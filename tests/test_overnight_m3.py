"""M3 — per-model request settings, with today's behaviour kept for
gemini-2.5-flash; and the model-matrix tool's guards (it is never run here).
Facts and sources: docs/MODEL_MIGRATION.md."""

from __future__ import annotations

import json

import pytest

from tests.contract import run_a_driver as D  # noqa: F401  (bootstraps imports)

from connectors.gemini_client import GeminiClient, model_profile  # noqa: E402


def _gen(model, **kw):
    cl = GeminiClient(api_key="offline-test-key")
    return cl._gen_config(model, kw.get("temperature", 0.0), kw.get("max_tokens", 8192),
                          kw.get("schema"), kw.get("budget"))


def test_gemini_2_5_flash_sends_exactly_what_it_sent_before():
    assert _gen("gemini-2.5-flash", budget=1024, schema={"type": "OBJECT"}) == {
        "temperature": 0.0, "maxOutputTokens": 8192,
        "responseMimeType": "application/json",
        "responseSchema": {"type": "OBJECT"},
        "thinkingConfig": {"thinkingBudget": 1024}}
    assert _gen("gemini-2.5-flash-lite") == {
        "temperature": 0.0, "maxOutputTokens": 8192,
        "responseMimeType": "application/json"}


@pytest.mark.parametrize("model,level", [
    ("gemini-3.5-flash-lite", "minimal"),
    ("gemini-3.6-flash", "low"),
    ("gemini-3.8-flash", "low"),
])
def test_gemini_3_drops_temperature_and_sends_a_thinking_level(model, level):
    g = _gen(model, budget=1024)
    assert "temperature" not in g
    assert g["thinkingConfig"] == {"thinkingLevel": level}


def test_gemini_3_8_never_gets_minimal():
    assert model_profile("gemini-3.8-flash")["thinking_level"] != "minimal"


def test_profiles_are_configurable(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL_PROFILES",
                       json.dumps({"gemini-3.6-flash": {"thinking_level": "medium",
                                                        "temperature": True}}))
    g = _gen("gemini-3.6-flash")
    assert g["thinkingConfig"] == {"thinkingLevel": "medium"}
    assert g["temperature"] == 0.0


def test_a_bad_override_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL_PROFILES", "not json")
    assert model_profile("gemini-2.5-flash")["thinking"] == "budget"


def test_the_live_cap_is_configurable_but_never_removable(monkeypatch):
    from tests.tools import live_cap
    monkeypatch.setenv("LIVE_CAP_MAX_CALLS", "50")
    monkeypatch.setenv("LIVE_CAP_MAX_USD", "1.00")
    assert live_cap.limits() == (50, 1.00)
    for bad in ("0", "-1", "inf", "nan", "100000", "none"):
        monkeypatch.setenv("LIVE_CAP_MAX_CALLS", bad)
        with pytest.raises(ValueError):
            live_cap.limits()
    monkeypatch.setenv("LIVE_CAP_MAX_CALLS", "50")
    for bad in ("0", "inf", "1000", "x"):
        monkeypatch.setenv("LIVE_CAP_MAX_USD", bad)
        with pytest.raises(ValueError):
            live_cap.limits()


def _matrix():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "tools" / "model_matrix.py"
    spec = importlib.util.spec_from_file_location("model_matrix", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_matrix_refuses_to_run_without_a_key(monkeypatch, tmp_path):
    M = _matrix()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        M.main(["--out", str(tmp_path)])
    assert "GEMINI_API_KEY" in str(e.value)


def test_the_matrix_plan_is_8_documents_by_5_models_under_the_caps():
    M = _matrix()
    assert len(M.DOCUMENTS) == 8 and len(M.MODELS) == 5
    assert M.MAX_CALLS == 50 and M.MAX_USD == 1.00
    assert all(g.endswith(".json") for _rel, _sheet, g in M.DOCUMENTS)
