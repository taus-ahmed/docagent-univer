"""
Opt-in retention (C1): DATA_RETENTION_DAYS and the daily purge.

Never runs at 0; purges only jobs past the period, finished, not deleted; one
firm at a time, and a purge of one firm cannot touch another's jobs; it uses
the same purge_job as the hard-delete route (files verified gone first).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

RA, RB = "rtAfirm", "rtBfirm"
NOW = datetime(2026, 10, 25, 12, 0)


@pytest.fixture
def local(_scratch_storage):
    from app.core.storage import get_storage
    return get_storage()


def _job(db, firm, local, age_days, status="completed"):
    from app.models.models import DocumentResult, ExtractionJob
    done = NOW - timedelta(days=age_days)
    j = ExtractionJob(client_id=firm, status=status, total_docs=1, input_source="upload",
                      created_at=done, completed_at=done if status != "processing" else None)
    db.add(j); db.commit(); db.refresh(j)
    key, _ = local.save_upload(b"%PDF-1.4 x", "r.pdf", j.id, client_id=firm)
    db.add(DocumentResult(job_id=j.id, filename="r.pdf", original_filename="r.pdf",
                          extraction_json="{}", s3_key=key))
    db.commit()
    return j


def _files(local, firm, jid):
    return local.count_prefix(local.job_prefix(firm, jid))


def _deleted(db, jid):
    from app.models.models import ExtractionJob
    db.expire_all()
    return bool(db.get(ExtractionJob, jid).marks().get("deleted"))


def test_zero_means_off_and_starts_nothing(db, local, monkeypatch):
    from app.config import settings
    from app.core import retention
    monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", 0)
    old = _job(db, RA, local, 4000)
    assert retention.start_daily_purge() is None
    assert retention.purge_expired(db, now=NOW) == {"firms": 0, "purged": 0, "failed": 0}
    assert not _deleted(db, old.id) and _files(local, RA, old.id) == 1


def test_only_jobs_past_the_period_are_purged(db, local):
    from app.core.retention import purge_firm
    old, young = _job(db, RA, local, 31), _job(db, RA, local, 29)
    running = _job(db, RA, local, 90, status="processing")
    r = purge_firm(db, RA, 30, now=NOW)
    assert old.id in r["purged"] and young.id not in r["purged"]
    assert running.id not in r["purged"]
    assert _deleted(db, old.id) and _files(local, RA, old.id) == 0
    assert not _deleted(db, young.id) and _files(local, RA, young.id) == 1
    assert not _deleted(db, running.id)


def test_a_purge_of_one_firm_never_touches_another(db, local):
    from app.core.retention import purge_firm
    a, b = _job(db, RA, local, 100), _job(db, RB, local, 100)
    r = purge_firm(db, RA, 30, now=NOW)
    assert a.id in r["purged"] and b.id not in r["purged"]
    assert not _deleted(db, b.id) and _files(local, RB, b.id) == 1


def test_every_firm_is_handled_and_the_log_names_no_firm(db, local, capsys):
    from app.core.retention import purge_expired
    a, b = _job(db, RA, local, 100), _job(db, RB, local, 100)
    t = purge_expired(db, days=30, now=NOW)
    assert t["purged"] >= 2 and _deleted(db, a.id) and _deleted(db, b.id)
    out = capsys.readouterr().out
    assert "[RETENTION]" in out and RA not in out and RB not in out and "r.pdf" not in out


def test_a_purged_job_is_marked_by_retention_and_not_purged_twice(db, local):
    from app.core.retention import purge_firm
    from app.models.models import ExtractionJob
    j = _job(db, RA, local, 100)
    purge_firm(db, RA, 30, now=NOW)
    db.expire_all()
    assert db.get(ExtractionJob, j.id).marks()["deleted"]["by"] == "retention"
    assert j.id not in purge_firm(db, RA, 30, now=NOW)["purged"]


def test_files_that_will_not_delete_leave_the_job_unmarked(db, local, monkeypatch):
    from app.core.retention import purge_firm
    j = _job(db, RA, local, 100)
    monkeypatch.setattr(type(local), "delete_prefix", lambda self, p: 0)
    r = purge_firm(db, RA, 30, now=NOW)
    assert j.id in r["failed"] and not _deleted(db, j.id)


def test_the_daily_task_starts_when_on(monkeypatch):
    from app.config import settings
    from app.core import retention
    monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", 30)
    monkeypatch.setattr(retention, "FIRST_RUN_DELAY_SEC", 3600)
    stop = retention.start_daily_purge()
    assert stop is not None
    stop.set()
