"""
Environment bootstrap for the accuracy harness.

Everything that touches the extraction pipeline must call ``bootstrap()``
BEFORE importing any ``app.*`` or engine module, because:

- ``app.config.settings`` is built once at import time from os.environ plus a
  CWD-relative ``.env`` file. We pre-load ``backend/.env`` into os.environ and
  chdir to ``backend/`` so relative paths (``./storage``, ``debug_output/``)
  land where production's layout puts them.
- Production runs ``USE_NEW_EXTRACTOR=true``, ``PRIMARY_LLM=gemini``,
  ``GEMINI_MODEL=gemini-2.5-flash-lite`` (audit 2026-08-17 §4). Local
  ``backend/.env`` does NOT set these, so without this bootstrap the harness
  would measure the dead legacy pipeline instead of what production runs.
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
PRODUCTION_PARITY_ENV = {
    "USE_NEW_EXTRACTOR": "true",
    "PRIMARY_LLM": "gemini",
    "GEMINI_MODEL": "gemini-2.5-flash-lite",
}

_bootstrapped = False


def bootstrap(production_parity: bool = True) -> None:
    """Idempotent. Load backend/.env, force production-parity extraction
    config, put engine/backend on sys.path, chdir to backend/."""
    global _bootstrapped
    if _bootstrapped:
        return

    # 1. backend/.env -> os.environ (existing environment wins)
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

    # 4. Relative paths (./storage, debug_output/) resolve as in production.
    os.chdir(BACKEND_DIR)

    _bootstrapped = True
