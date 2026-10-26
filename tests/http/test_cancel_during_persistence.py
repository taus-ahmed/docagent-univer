"""A cancel that lands while a file's results are being SAVED (Run 15, item 5).

The job thread checked for a cancel once after reading a file, then built and
flushed one DocumentResult per record. A cancel raised while those were being
built (a checkpoint, or the cancel check itself) left the file's earlier
records flushed — and the cancelled branch then COMMITTED them beside a
`cancelled` row for the same file: a job saying "cancelled" holding a result
for the in-flight file that looked final and was not complete.

Now a file is persisted as one transaction, after one last cancel check: a
cancel before that check discards the whole file (listed as cancelled); a
cancel after it lets the file complete and be saved whole.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.http.test_job_cancel import _job, _ok, _rows, _set_status, worker  # noqa: E402,F401


def _two(name):
    a, b = _ok(name), _ok(name)
    b.extracted_data = {"needs_review": False, "validation": {},
                        "extracted_fields": {"B1": "2"}}
    return [a, b]


def test_a_cancel_raised_while_building_a_files_records_discards_the_file(
        db, users, worker, _db_url, monkeypatch):
    """Codex's case: the cancel fires DURING construction of record 2 of 2."""
    import app.services.job_worker as jw
    from cancellation import Cancelled
    from app.models.models import ExtractionJob
    job = _job(db, users["acme2"], status="pending", n=3)
    second_records = []
    real = jw._value_requires_review

    def cancel_on_the_fourth(extracted):
        fields = extracted.get("extracted_fields") if isinstance(extracted, dict) else None
        if isinstance(fields, dict) and fields.get("B1") == "2" \
                and id(extracted) not in second_records:
            second_records.append(id(extracted))
        if len(second_records) == 2:              # file b, record 2
            _set_status(_db_url, job.id, "cancelled")
            raise Cancelled()
        return real(extracted)
    monkeypatch.setattr(jw, "_value_requires_review", cancel_on_the_fourth)

    worker(job, ["a.pdf", "b.pdf", "c.pdf"],
           lambda _o, path, *a, **k: _two(Path(path).name))
    assert _rows(db, job.id) == [("a.pdf", "cheque", True),
                                 ("a.pdf", "cheque", True),
                                 ("b.pdf", "cancelled", False),
                                 ("c.pdf", "cancelled", False)]
    db.expire_all()
    j = db.get(ExtractionJob, job.id)
    assert j.status == "cancelled" and j.successful == 2
    assert "Cancelled after 1 of 3" in j.progress_message


def test_a_cancel_after_the_last_check_lets_the_file_finish_whole(
        db, users, worker, _db_url, monkeypatch):
    """The cancel lands after the pre-persist check: the file is saved whole,
    and the job says so."""
    import app.services.job_worker as jw
    from app.models.models import ExtractionJob
    job = _job(db, users["acme2"], status="pending", n=3)
    real = jw._commit_file

    def cancel_then_commit(session, *a, **k):
        if not getattr(cancel_then_commit, "done", False):
            cancel_then_commit.done = True
            _set_status(_db_url, job.id, "cancelled")
        return real(session, *a, **k)
    monkeypatch.setattr(jw, "_commit_file", cancel_then_commit)

    worker(job, ["a.pdf", "b.pdf", "c.pdf"],
           lambda _o, path, *a, **k: _two(Path(path).name))
    assert _rows(db, job.id) == [("a.pdf", "cheque", True),
                                 ("a.pdf", "cheque", True),
                                 ("b.pdf", "cancelled", False),
                                 ("c.pdf", "cancelled", False)]
    db.expire_all()
    j = db.get(ExtractionJob, job.id)
    assert j.status == "cancelled" and j.successful == 2
    assert "Cancelled after 1 of 3" in j.progress_message


def test_a_cancel_before_the_last_check_discards_the_file(
        db, users, worker, _db_url, monkeypatch):
    """The cancel lands after reading, during post-processing, before the
    pre-persist check: the file is discarded."""
    import app.services.job_worker as jw
    job = _job(db, users["acme2"], status="pending", n=2)
    real = jw._flag_summary
    seen = {"n": 0}

    def cancel_during(flags):
        seen["n"] += 1
        _set_status(_db_url, job.id, "cancelled")
        return real(flags)
    monkeypatch.setattr(jw, "_flag_summary", cancel_during)

    def flagged(_o, path, *a, **k):
        r = _ok(Path(path).name)
        r.extracted_data["validation"] = {"flagged_fields": [
            {"ref": "B1", "value": "1", "reason": "x"}]}
        return [r]
    worker(job, ["a.pdf", "b.pdf"], flagged)
    assert seen["n"] == 1
    assert _rows(db, job.id) == [("a.pdf", "cancelled", False),
                                 ("b.pdf", "cancelled", False)]


def test_a_database_error_saving_one_file_fails_that_file_whole(
        db, users, worker, _db_url, monkeypatch):
    import app.services.job_worker as jw
    from app.models.models import ExtractionJob
    job = _job(db, users["acme2"], status="pending", n=2)
    real = jw._commit_file
    calls = {"n": 0}

    def fail_first(session, staged, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            for doc, *_ in staged:
                session.add(doc)
            session.flush()
            raise RuntimeError("disk full")
        return real(session, staged, *a, **k)
    monkeypatch.setattr(jw, "_commit_file", fail_first)
    worker(job, ["a.pdf", "b.pdf"], lambda _o, path, *a, **k: _two(Path(path).name))
    rows = _rows(db, job.id)
    assert ("b.pdf", "cheque", True) in rows and rows.count(("b.pdf", "cheque", True)) == 2
    assert [r for r in rows if r[0] == "a.pdf" and r[2]] == [], rows
    db.expire_all()
    j = db.get(ExtractionJob, job.id)
    assert j.successful == 2 and j.failed == 1


@pytest.mark.parametrize("saved", [0, 2])
def test_restart_recovery_says_what_was_saved(app, db, users, monkeypatch, saved):
    import app.models as models
    from app import main
    from app.models.models import DocumentResult, ExtractionJob
    monkeypatch.setattr(models, "SessionLocal", app.state._sessionmaker)
    running = _job(db, users["acme2"], status="processing", n=5)
    for k in range(saved):
        db.add(DocumentResult(job_id=running.id, filename=f"{k}.pdf",
                              extraction_json="{}"))
    db.commit()
    main._release_stranded_jobs()
    db.expire_all()
    j = db.get(ExtractionJob, running.id)
    assert j.status == "failed"
    if saved:
        assert "Nothing was saved" not in j.error_message
        assert "2 of 5" in j.error_message
    else:
        assert "Nothing was saved" in j.error_message
