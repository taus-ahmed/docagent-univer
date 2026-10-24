"""The backend, project and engine directories, and the engine on sys.path.

The same values `extract.py` computes for itself; split modules import them
from here (importing this module first puts the engine directory on sys.path,
appended exactly as `extract.py` does, so `log_safety` and friends resolve).
"""
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent.parent
_project_dir = _backend_dir.parent
_engine_dir = _backend_dir / "engine"

if str(_engine_dir) not in sys.path:
    sys.path.append(str(_engine_dir))
