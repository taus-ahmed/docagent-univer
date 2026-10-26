"""Option model calls are capped per job and counted toward the month (Part A4)."""


def test_grant_counts_each_call_against_job_and_month(db, users, monkeypatch):
    from app.models.models import ExtractionJob
    from app.services.job_worker import _grant_option_call
    from app.config import settings
    monkeypatch.setattr(settings, "OPTION_MAX_CALLS_PER_JOB", 2, raising=False)
    j = ExtractionJob(user_id=users["acme2"].id, client_id="acme_001", status="processing",
                      total_docs=1, input_source="upload")
    j.set_mark("pages", 1)
    db.add(j); db.commit()
    assert _grant_option_call(db, j) and _grant_option_call(db, j)
    assert not _grant_option_call(db, j)                   # per-job cap
    assert j.marks()["pages"] == 3                          # each call counted as a page
