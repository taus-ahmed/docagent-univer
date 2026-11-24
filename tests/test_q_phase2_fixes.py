"""Run Q Phase 2 — the three largest engine causes found by replaying the real
model answers (docs/RUN_Q_PHASE2_FINDINGS.md). Each unit test uses values and
geometry taken from the real replayed jobs. Each `_real` test replays the
stored answer and skips when local_docs/raw is absent."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def _replay(job_id):
    import replay_raw
    if not replay_raw.has_raw(job_id):
        pytest.skip(f"local_docs/raw/{job_id} not present")
    rep = replay_raw.replay_job(job_id)
    if not rep["docs"]:
        pytest.skip(f"job {job_id}: {rep['skipped']}")
    return rep


def _reasons(rep):
    out = []
    for _m, ed, _x in rep["docs"]:
        for f in ed["validation"]["flagged_fields"]:
            out.append((str(f.get("ref")), str(f.get("value")), str(f.get("reason"))))
    return out


# ── cause 1: a long identifier is not a phone number ─────────────────────────

class TestLongIdentifierIsNotAPhone:
    @pytest.mark.parametrize("value,label", [
        ("702000000803", "Batch"),                 # job 73, 12 digits
        ("08632520260515", "INVOICE"),             # job 72, 14 digits
        ("980104801-062326", "INVOICE"),           # job 72
    ])
    def test_one_datum(self, value, label):
        from slot_extractor import _single_datum
        assert _single_datum(value, label)

    @pytest.mark.parametrize("value", [
        "Robert Chen 555-123-4567",
        "Robert Chen (800) 544-5555",
        "Robert Chen 8005445555",
    ])
    def test_a_real_phone_beside_a_name_still_fails(self, value):
        from slot_extractor import _single_datum
        assert not _single_datum(value, "Contact Name")

    def test_real_job_73_batch_numbers(self):
        rep = _replay(73)
        bad = [r for r in _reasons(rep) if "more than one piece" in r[2]
               and r[0].startswith("SUMMARY BY BATCH")]
        assert bad == []
