"""
A static gate: no undefined name anywhere in the backend.

WHY THIS IS A TEST AND NOT A ONE-OFF. Phase 8 shipped
`_resolve_source(storage, fp)` inside `_run_extraction_sync`, where `storage`
is a request dependency that does not exist. Python raises NameError only when
the line executes, the line lived in a background thread, and the thread's
per-document `except` turned it into "this document failed" — so every upload
failed while the job reported `completed`. Nothing in 450 tests saw it.

Pyflakes finds it by reading the file. One undefined name shipped a
total-failure bug, so the check runs on every commit rather than the day
somebody thinks to run it.

Scope is deliberately narrow: undefined names only. Pyflakes reports plenty of
other things — unused imports, shadowed builtins, star imports — and turning
those into failures across a codebase this size would mean a wave of unrelated
edits. `_UNDEFINED` is the class of finding that means "this line cannot run".
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TARGETS = [REPO / "backend" / "app", REPO / "backend" / "engine",
           REPO / "backend" / "scripts"]

#: Pyflakes messages that mean a name is READ where nothing has defined it.
#:
#: Matched precisely. "local variable" alone also matches "assigned to but
#: never used", which is untidy but harmless — nine of those exist today, and
#: sweeping them in would bury the one class of finding that means the line
#: cannot run. The two phrases below are the ones that do.
_UNDEFINED = ("undefined name", "referenced before assignment")


def _pyflakes(paths):
    """Run pyflakes as a subprocess and return its report lines.

    A checker that cannot run is a failure, not a pass — the same rule the
    schema-drift check follows. If pyflakes is missing, this test fails and
    says how to install it, rather than skipping and reporting green.
    """
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        pytest.fail(
            "pyflakes is not installed, so the undefined-name gate cannot "
            "run — and a check that cannot run must not report success. "
            "Install it: pip install -r backend/requirements-dev.txt")

    proc = subprocess.run(
        [sys.executable, "-m", "pyflakes", *[str(p) for p in paths]],
        capture_output=True, text=True, cwd=str(REPO))
    # Pyflakes exits 1 when it has findings and 2 on an internal error.
    assert proc.returncode in (0, 1), (
        f"pyflakes failed to run (exit {proc.returncode}):\n{proc.stderr}")
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


class TestNoUndefinedNames:

    def test_the_backend_has_no_undefined_names(self):
        findings = [ln for ln in _pyflakes(TARGETS)
                    if any(k in ln.lower() for k in _UNDEFINED)]
        assert not findings, (
            "undefined name(s) in the backend - each one is a line that "
            "raises NameError the moment it executes:\n  "
            + "\n  ".join(findings))

    def test_the_gate_actually_detects_one(self, tmp_path):
        """The gate must be able to fail.

        A linter invoked with a wrong path, a bad flag, or a swallowed exit
        code prints nothing and passes forever. This plants a file that IS
        broken and requires the checker to say so.
        """
        bad = tmp_path / "planted.py"
        bad.write_text("def f():\n    return not_a_real_name\n", encoding="utf-8")
        findings = [ln for ln in _pyflakes([bad])
                    if any(k in ln.lower() for k in _UNDEFINED)]
        assert findings, (
            "pyflakes reported nothing for a file with an undefined name — "
            "the gate is not actually checking anything")
