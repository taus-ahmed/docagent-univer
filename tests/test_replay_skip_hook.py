"""DOCAGENT_REPLAY_ENV=skip skips ONLY tests carrying the `replay` marker
(Run 15, item 10).

A ReplayEnvironmentError raised by a test nobody marked `replay` used to be
skipped too, with a line asking for the marker — so a test that silently
started depending on the replay cache went quiet in CI instead of failing.
Now it FAILS under every policy; a marked one is skipped, named, and the
summary counts both.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CASES = "tests/fixtures/replay_hook_cases.py"


def _run(policy):
    env = dict(os.environ, DOCAGENT_REPLAY_ENV=policy, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-rfs", CASES], cwd=REPO, env=env, capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def test_skip_policy_skips_marked_and_fails_unmarked():
    code, out = _run("skip")
    last = out.strip().splitlines()[-1]
    assert code != 0, out[-1500:]
    assert "1 failed" in last and "1 passed" in last and "1 skipped" in last, last
    assert "FAILED tests/fixtures/replay_hook_cases.py::test_unmarked_replay_mismatch" in out
    assert "1 replay-dependent test(s) SKIPPED" in out
    assert "1 UNMARKED test(s) raised ReplayEnvironmentError and FAILED" in out


def test_require_policy_fails_both():
    code, out = _run("require")
    last = out.strip().splitlines()[-1]
    assert code != 0
    assert "2 failed" in last and "skipped" not in last, last
