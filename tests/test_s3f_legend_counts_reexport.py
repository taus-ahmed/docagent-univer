"""Run S, Stage 3f — Legend counts vs marked cells (jobs 46, 48, 51).

The frozen staging exports (local_docs/batch1_exports) were written by the
OLD writer, which marked only slots holding a value: jobs 46, 48 and 51
report 3, 12 and 2 empty-and-flagged values and paint no grey cell. That is
the strict xfail `test_batch1_real_defects::test_09`; no code change can
alter files already written, so that marker stays (tests/KNOWN_FAILING.md).

This test is the re-export the marker asks for: every job 40-55 rebuilt from
the extraction results STAGING STORED (local_docs/raw/<job>/docs/*.json,
`extraction_json`, not a replay), through today's writer, and each Legend
count compared with the cells actually painted. Skips without local_docs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
RAW = ROOT / "local_docs" / "raw"


def _stored(job):
    d = RAW / str(job) / "docs"
    if not d.is_dir():
        return None
    out = []
    for p in sorted(d.glob("*.json"), key=lambda p: int(p.stem)):
        doc = json.loads(p.read_text(encoding="utf-8"))
        ed = doc.get("extraction_json") or {}
        if isinstance(ed, str):
            ed = json.loads(ed or "{}")
        out.append((doc, ed, []))
    return out


@pytest.mark.parametrize("job", [46, 48, 51] + [j for j in range(40, 56)
                                                if j not in (46, 48, 51)])
def test_reexported_legend_counts_equal_marked_cells(job, tmp_path):
    docs = _stored(job)
    if docs is None:
        pytest.skip(f"local_docs/raw/{job} not present (git-ignored real data)")
    import openpyxl
    import replay_raw
    from tests.test_batch1_real_defects import _legend_counts, _marked_counts
    replay_raw._setup()
    tpl = json.loads((RAW / str(job) / "template.json").read_text(encoding="utf-8"))
    p = replay_raw.write_workbook(job, {"docs": docs, "template": tpl},
                                  tmp_path / f"job_{job}.xlsx")
    wb = openpyxl.load_workbook(p)
    assert _legend_counts(wb) == _marked_counts(wb)
