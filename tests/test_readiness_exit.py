"""Review-3 F9: a hung readiness check cannot keep the process alive.

`_bounded` ran each check on a ThreadPoolExecutor. Its workers are joined at
interpreter exit, so a probe stuck on a dependency that never answers kept
the process from exiting after the probe itself had long since timed out.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from app.core import readiness  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_a_blocking_check_times_out(monkeypatch):
    monkeypatch.setattr(readiness, "CHECK_TIMEOUT", 0.2)
    gate = threading.Event()

    def blocks_forever():
        gate.wait()
        return "ok"
    t = time.perf_counter()
    try:
        assert readiness._bounded(blocks_forever) == "fail:timeout"
        assert time.perf_counter() - t < 2
        # the next probe does not stack another thread on the stuck one
        assert readiness._bounded(blocks_forever) == "fail:busy"
    finally:
        gate.set()


def test_a_check_that_raises_names_the_exception_only():
    def boom():
        raise ConnectionError("postgresql://user:secret@host/db")
    assert readiness._bounded(boom) == "fail:ConnectionError"


def test_a_good_check_answers(monkeypatch):
    assert readiness._bounded(lambda: "ok") == "ok"


def test_the_process_exits_with_a_check_still_hung():
    prog = (
        "import sys, threading\n"
        f"sys.path[:0] = [r'{ROOT / 'backend'}', r'{ROOT / 'backend' / 'engine'}']\n"
        "from app.core import readiness\n"
        "readiness.CHECK_TIMEOUT = 0.2\n"
        "def hang():\n"
        "    threading.Event().wait()\n"
        "print(readiness._bounded(hang), flush=True)\n"
    )
    t = time.perf_counter()
    try:
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                           timeout=30, cwd=str(ROOT / "backend"))
    except subprocess.TimeoutExpired:
        pytest.fail("the interpreter did not exit: the hung check's thread was joined")
    assert r.stdout.decode().strip() == "fail:timeout", r.stderr.decode()[-1500:]
    assert time.perf_counter() - t < 25
