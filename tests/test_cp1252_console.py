"""Review-3 F12: a CP1252 console cannot crash worker startup.

`Orchestrator.__init__` — the first thing every job thread does — prints a
Rich panel with box drawing and an emoji. On a stdout whose encoding is
CP1252 that raised UnicodeEncodeError, so the job failed before its first
document. Run with PYTHONIOENCODING=cp1252 in a fresh interpreter, as a
Windows console or a pipe would give it.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def _run(code):
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0",
           "PRIMARY_LLM": "stub", "LLM_FALLBACKS": "", "ENVIRONMENT": "development"}
    prog = (f"import sys; sys.path[:0] = [r'{BACKEND}', r'{BACKEND / 'engine'}']\n"
            "import app.services.paths\n" + code)
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                       env=env, cwd=str(BACKEND), timeout=120)
    return r.returncode, r.stdout.decode("cp1252", "replace"), r.stderr.decode("utf-8", "replace")


def test_worker_startup_survives_a_cp1252_stdout():
    code, out, err = _run(
        "assert sys.stdout.encoding.lower() == 'cp1252', sys.stdout.encoding\n"
        "from orchestrator import Orchestrator\n"
        "Orchestrator(client_schema_path='engine/demo_accounting.yaml')\n"
        "print('constructed')\n")
    assert code == 0 and "constructed" in out, err[-1500:]
    assert "UnicodeEncodeError" not in err


def test_safe_stdio_makes_print_replace_not_raise():
    code, out, err = _run(
        "from log_safety import safe_stdio\n"
        "safe_stdio()\n"
        "print('ok \\U0001f916 \\u2192 \\u2713 done')\n")
    assert code == 0 and "ok ? ? ? done" in out, err[-1500:]


def test_a_utf8_stream_is_left_alone():
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    prog = (f"import sys; sys.path[:0] = [r'{BACKEND / 'engine'}']\n"
            "from log_safety import safe_stdio\n"
            "safe_stdio(); print(sys.stdout.errors); print('\\u2713')\n")
    r = subprocess.run([sys.executable, "-c", prog], capture_output=True, env=env, timeout=60)
    out = r.stdout.decode("utf-8")
    assert r.returncode == 0 and out.splitlines() == ["strict", "\u2713"], out
