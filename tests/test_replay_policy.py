"""DOCAGENT_REPLAY_ENV: a replay environment mismatch is a named skip in CI
and an error everywhere else — never a silent pass (tests/conftest.py).

Runs a replay-dependent test file in a subprocess with Poppler removed from
PATH, which is the mismatch the preflight is guaranteed to detect.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TARGET = "tests/test_transposed_case.py"


def _run(policy: str):
    env = dict(os.environ)
    tool = shutil.which("pdftoppm")
    if tool:
        drop = os.path.normcase(str(Path(tool).parent))
        env["PATH"] = os.pathsep.join(
            p for p in env.get("PATH", "").split(os.pathsep)
            if os.path.normcase(p.rstrip("\\/")) != drop.rstrip("\\/"))
    env["DOCAGENT_REPLAY_ENV"] = policy
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        TARGET], cwd=REPO, env=env, capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace")


@pytest.fixture(scope="module")
def no_poppler_possible():
    env_path = os.environ.get("PATH", "")
    tool = shutil.which("pdftoppm")
    if tool and shutil.which("pdftoppm", path=os.pathsep.join(
            p for p in env_path.split(os.pathsep)
            if os.path.normcase(p.rstrip("\\/")) != os.path.normcase(str(Path(tool).parent)))):
        pytest.skip("pdftoppm is on PATH twice; cannot simulate its absence")


def test_skip_policy_skips_by_name(no_poppler_possible):
    code, out = _run("skip")
    assert code == 0, out[-2000:]
    assert "REPLAY ENVIRONMENT MISMATCH" in out
    assert "replay-dependent test(s) SKIPPED" in out
    assert " passed" not in out.splitlines()[-1] or "skipped" in out.splitlines()[-1]


def test_require_policy_fails(no_poppler_possible):
    code, out = _run("require")
    assert code != 0, out[-2000:]
    assert "skipped" not in out.splitlines()[-1]
