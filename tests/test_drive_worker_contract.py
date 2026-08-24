"""
A pin on the Drive path's broken call into the extraction worker.

`drive.py` calls the job runner with four arguments:

    _run_extraction_sync(job_id, downloaded, schema_path, db_url)

`_run_extraction_sync` requires eight. The call raises TypeError before it
reaches a single line of the worker, so a watched Drive folder cannot extract
anything. This is not new and it is not being fixed here — it is consistent
with the runbook's known-issue #2, "the Drive tab leads nowhere", and the Drive
path needs a proper repair rather than an argument list.

What this file does is stop it getting worse quietly. The mismatch is now
asserted, so:

  * changing `_run_extraction_sync`'s signature fails this test rather than
    silently moving the breakage somewhere new;
  * fixing `drive.py` fails this test, which is the signal to delete the pin
    and write a real Drive test;
  * nobody reads the four-argument call as working code.

The check is static — the AST of the call site and the signature of the target.
Nothing is executed, so pinning a broken path costs no Drive credentials, no
network and no job rows.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

DRIVE_PY = bs.BACKEND_DIR / "app" / "api" / "routes" / "drive.py"


def _call_sites(path: Path, func_name: str):
    """Every call to `func_name` in `path`, as (lineno, n_positional, kwnames)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = (f.id if isinstance(f, ast.Name)
                else f.attr if isinstance(f, ast.Attribute) else None)
        if name == func_name:
            out.append((node.lineno, len(node.args),
                        sorted(k.arg for k in node.keywords if k.arg)))
    return out


@pytest.fixture(scope="module")
def worker_signature():
    from app.api.routes.extract import _run_extraction_sync
    return inspect.signature(_run_extraction_sync)


class TestDrivePathIsPinnedAsBroken:

    def test_the_worker_still_requires_eight_arguments(self, worker_signature):
        required = [p.name for p in worker_signature.parameters.values()
                    if p.default is inspect.Parameter.empty]
        assert required == ["job_id", "file_keys", "schema_path", "db_url",
                            "template_data", "project_dir", "backend_dir",
                            "engine_dir"], required

    def test_drive_still_calls_it_with_four(self):
        sites = _call_sites(DRIVE_PY, "_run_extraction_sync")
        assert len(sites) == 1, (
            f"expected exactly one call site in drive.py, found {sites}")
        lineno, n_pos, kwnames = sites[0]
        assert (n_pos, kwnames) == (4, []), (
            f"drive.py:{lineno} now calls the worker with {n_pos} positional "
            f"argument(s) and keywords {kwnames}. If the Drive path has been "
            f"repaired, delete this file and write a real Drive test; if the "
            f"call merely changed shape, it is still broken and this pin needs "
            f"updating to say how.")

    def test_that_call_cannot_bind(self, worker_signature):
        """The consequence, stated rather than implied: those four arguments
        raise TypeError before the worker runs a single line."""
        with pytest.raises(TypeError) as e:
            worker_signature.bind(1, ["a-key"], "schema.yaml", "sqlite://")
        assert "missing" in str(e.value).lower(), str(e.value)

    def test_the_drive_path_is_recorded_as_known_broken(self):
        """A pin that nobody can find is a trap. The runbook's known-unfixed
        table is where an operator looks, so the entry has to exist."""
        runbook = (bs.REPO_DIR / "docs" / "DEPLOY-RUNBOOK.md").read_text(
            encoding="utf-8").casefold()
        assert "drive" in runbook, (
            "the Drive path is pinned as broken here but the deploy runbook "
            "does not mention it")
