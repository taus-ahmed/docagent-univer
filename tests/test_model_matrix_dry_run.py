"""tools/model_matrix.py --dry-run: every (document, model) job of the live
matrix is CONSTRUCTED offline, so the tool cannot silently break again.

It broke once already: `Orchestrator.__init__` gained `client_schema_path`,
the tool still called `Orchestrator()`, and every one of the 40 cells failed
with a TypeError the first time anyone paid to run it. The dry run builds the
same objects the live run builds (no key, no network), so that class of
breakage now fails here.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _matrix():
    path = ROOT / "tools" / "model_matrix.py"
    spec = importlib.util.spec_from_file_location("model_matrix_dry", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def M(monkeypatch):
    # main() sets these for the process; give them back afterwards.
    monkeypatch.setenv("DOCAGENT_TEST_NO_DOTENV", "1")
    for k in ("GEMINI_MODEL", "GEMINI_MODEL_FALLBACKS"):
        monkeypatch.setenv(k, os.environ.get(k, ""))
    try:
        from pydantic_settings.sources import DotEnvSettingsSource
        monkeypatch.setattr(DotEnvSettingsSource, "__call__", DotEnvSettingsSource.__call__)
    except ImportError:
        pass
    mod = _matrix()
    from tests.local_corpus import ROOTS
    missing = [rel for rel, _s, _g in mod.DOCUMENTS
               if not any((r / rel).is_file() for r in ROOTS)]
    if missing and os.environ.get("CI"):
        pytest.skip(f"git-ignored local corpus absent on CI: {missing[0]}")
    return mod


def test_dry_run_builds_every_job_without_a_key_or_network(M, monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import connectors.gemini_client as G
    real_post = G.GeminiClient._post

    assert M.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    n = len(M.DOCUMENTS) * len(M.MODELS)
    assert f"{n} of {n} jobs built" in out
    assert f"would make {n} calls, estimated cost $" in out
    assert "FAILED" not in out
    assert G.GeminiClient._post is real_post          # the offline patch is undone


def test_dry_run_fails_loudly_when_the_orchestrator_cannot_be_built(M, monkeypatch, capsys):
    import orchestrator

    class _OldSignature:                       # the shape of the original break
        def __init__(self, some_other_required_arg):
            raise AssertionError("unreachable")

    monkeypatch.setattr(orchestrator, "Orchestrator", _OldSignature)
    assert M.main(["--dry-run", "--docs", "pitt_sample_w2"]) == 2
    out = capsys.readouterr().out
    assert "FAILED: 5 job(s) cannot be constructed" in out
    assert "TypeError" in out


def test_dry_run_fails_loudly_on_a_job_whose_template_is_gone(M, monkeypatch, capsys):
    rel, _sheet, gold = M.DOCUMENTS[0]
    monkeypatch.setattr(M, "DOCUMENTS", [(rel, "No_Such_Sheet", gold)])
    assert M.main(["--dry-run", "--models", "gemini-2.5-flash"]) == 2
    assert "cannot be constructed" in capsys.readouterr().out


def test_unknown_docs_are_refused(M):
    with pytest.raises(SystemExit) as e:
        M.main(["--dry-run", "--docs", "not_a_document"])
    assert "unknown --docs" in str(e.value)


def test_a_client_left_on_another_model_is_refused(M, monkeypatch):
    """settings, the environment and every Gemini client must name the model
    being measured; the harness bootstrap's parity mode used to leave settings
    on gemini-2.5-flash-lite while the client was pinned to something else."""
    M._paths()
    from app.config import settings
    import connectors.gemini_client as G
    c = G.GeminiClient.__new__(G.GeminiClient)
    c._preferred = "gemini-2.5-flash"
    router = type("R", (), {"providers": [("gemini", c)]})()
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    assert M.model_mismatch("gemini-2.5-flash", router) is None
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite")
    why = M.model_mismatch("gemini-2.5-flash", router)
    assert why and "settings.GEMINI_MODEL='gemini-2.5-flash-lite'" in why
