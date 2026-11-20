"""Locate the git-ignored local corpus (PDFs and the real staging exports).

``local_docs/`` is git-ignored, so on CI it is absent.  A test that needs a
file from it calls ``local_file(relative)``: on a workstation a missing file is
an ERROR (a silently skipped reproduction proves nothing), and on CI (``CI``
set, as GitHub Actions does) it is a SKIP with a reason naming the file.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROOTS = (
    ROOT / "local_docs",
    ROOT / "local_docs" / "DocAgent_testdocs",
    ROOT.parent / "docagent-testdocs" / "DocAgent_testdocs",
)


def local_file(relative: str) -> Path:
    for root in ROOTS:
        candidate = root / relative
        if candidate.is_file():
            return candidate
    if os.environ.get("CI"):
        pytest.skip(f"git-ignored local corpus absent on CI: {relative}")
    raise AssertionError(f"required local corpus file is missing: {relative}")


def export(job: int) -> Path:
    """One of the 16 real staging exports, ``local_docs/batch1_exports``."""
    return local_file(f"batch1_exports/job_{job}_results.xlsx")
