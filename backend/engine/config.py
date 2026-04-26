"""
engine/config.py — Compatibility shim for the prototype engine.
Bridges all `from config import settings` calls in the engine files
to the v2 pydantic-settings config, so the engine never needs its own .env.
"""
import sys
from pathlib import Path

# Ensure backend root is on sys.path so app.config is importable
_engine_dir = Path(__file__).resolve().parent
_backend_dir = _engine_dir.parent

for _p in [str(_backend_dir), str(_engine_dir)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from app.config import settings
except ImportError:
    # Fallback: create a minimal settings object from environment
    import os
    from types import SimpleNamespace
    settings = SimpleNamespace(
        GROQ_API_KEY=os.environ.get("GROQ_API_KEY", ""),
        GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY", ""),
        DATABASE_URL=os.environ.get("DATABASE_URL", "sqlite:///./docagent.db"),
        STORAGE_BACKEND=os.environ.get("STORAGE_BACKEND", "local"),
        LLM_PROVIDER=os.environ.get("LLM_PROVIDER", "groq"),
        LLM_MODEL=os.environ.get("LLM_MODEL", "llama-3.2-90b-vision-preview"),
        MAX_FILES_PER_BATCH=int(os.environ.get("MAX_FILES_PER_BATCH", "20")),
        MAX_FILE_SIZE_MB=int(os.environ.get("MAX_FILE_SIZE_MB", "50")),
        SECRET_KEY=os.environ.get("SECRET_KEY", "change-me"),
        DEBUG=os.environ.get("DEBUG", "true").lower() == "true",
    )

# The prototype used BASE_DIR to find schemas/input/output folders.
BASE_DIR = _engine_dir
