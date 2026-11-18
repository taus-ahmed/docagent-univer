"""
Environment bootstrap for the accuracy harness.

Everything that touches the extraction pipeline must call ``bootstrap()``
BEFORE importing any ``app.*`` or engine module, because:

- ``app.config.settings`` is built once at import time from os.environ plus a
  CWD-relative ``.env`` file. Legacy runs may pre-load ``backend/.env``;
  acceptance and CI runs set ``DOCAGENT_TEST_NO_DOTENV=1`` and use explicit
  local test settings only.
- Production runs ``PRIMARY_LLM=gemini`` and
  ``GEMINI_MODEL=gemini-2.5-flash-lite`` (audit 2026-08-17 §4). Local
  ``backend/.env`` does not set the model, so without this bootstrap the
  harness would measure a different Gemini tier than production runs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_DIR / "tests"
BACKEND_DIR = REPO_DIR / "backend"
ENGINE_DIR = BACKEND_DIR / "engine"
GOLD_DIR = TESTS_DIR / "gold"
LABELS_DIR = GOLD_DIR / "labels"
TEMPLATES_DIR = GOLD_DIR / "templates"
PDF_DIR = TESTS_DIR / "test_pdfs"
CACHE_DIR = TESTS_DIR / "llm_cache"
REPORTS_DIR = TESTS_DIR / "reports"

# Production extraction config, per the 2026-08-17 audit of the Railway env.
# USE_NEW_EXTRACTOR was removed in Phase 2d — there is one pipeline now, so
# there is no longer a flag that could make local runs exercise different code
# than production.
PRODUCTION_PARITY_ENV = {
    "PRIMARY_LLM": "gemini",
    "GEMINI_MODEL": "gemini-2.5-flash-lite",
}

_bootstrapped = False


def chdir_backend() -> None:
    """Make relative paths (./storage) resolve as they do in
    production, where the process runs from backend/.

    Deliberately NOT done inside bootstrap(): bootstrap runs at pytest
    collection time, and changing the working directory there breaks the
    rootdir-relative ``testpaths`` in pytest.ini. Only code that actually
    executes the pipeline needs this.
    """
    if Path.cwd().resolve() != BACKEND_DIR.resolve():
        os.chdir(BACKEND_DIR)


def bootstrap(production_parity: bool = True) -> None:
    """Idempotent. Load backend/.env, force production-parity extraction
    config, put engine/backend on sys.path. Does not change directory."""
    global _bootstrapped
    if _bootstrapped:
        return

    # 1. Legacy opt-in: backend/.env -> os.environ (existing environment wins).
    # Acceptance/CI set DOCAGENT_TEST_NO_DOTENV=1 so owner credentials are
    # never read by a test run.
    no_dotenv = os.environ.get("DOCAGENT_TEST_NO_DOTENV") == "1"
    if no_dotenv:
        # app.config uses pydantic-settings' DotEnvSettingsSource when it is
        # imported later. Disable that source in this test process as well as
        # skipping the explicit legacy preload above.
        try:
            from pydantic_settings.sources import DotEnvSettingsSource
            DotEnvSettingsSource.__call__ = lambda self: {}
        except ImportError:
            pass
    else:
        try:
            from dotenv import dotenv_values
            for k, v in (dotenv_values(BACKEND_DIR / ".env") or {}).items():
                if v is not None:
                    os.environ.setdefault(k, v)
        except ImportError:
            pass

    # 2. Production-parity flags override whatever .env said, so the harness
    #    always measures the engine production actually runs.
    if production_parity:
        os.environ.update(PRODUCTION_PARITY_ENV)

    # Replay mode needs no real key, but LLMRouter.__init__ raises without one.
    os.environ.setdefault("GEMINI_API_KEY", "offline-replay-placeholder")

    # 3. Import paths, mirroring extract.py's sys.path injection.
    for p in (str(ENGINE_DIR), str(BACKEND_DIR), str(REPO_DIR)):
        if p not in sys.path:
            sys.path.insert(0, p)

    _bootstrapped = True
