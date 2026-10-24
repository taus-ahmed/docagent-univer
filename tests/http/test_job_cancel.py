"""
Cancelling a job, and a job left running by a dead process (J1/J2).

Cancel (DELETE /api/jobs/{id}): owner or an admin in scope; another firm's job
is 404; a second cancel says it already was. The job thread stops at its next
checkpoint — before a file, between pages, before a model call — keeps the
files that FINISHED, discards the one in flight (never stored as if final),
and lists every unfinished file as a `cancelled` row. The job stays
`cancelled` with a visible reason; the thread never overwrites it.

Restart: a job left pending/processing is failed at boot with the reason
"Interrupted by restart"; nothing is deleted.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def _job(db, owner, status="processing", n=3, cid="acme_001"):
    from app.models.models import ExtractionJob
    j = ExtractionJob(user_id=owner.id, client_id=cid, status=status,
                      total_docs=n, input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def _ok(name):
    return SimpleNamespace(filename=name, document_type="cheque", success=True,
                           extracted_data={"needs_review": False, "validation": {},
                                           "extracted_fields": {"B1": "1"}},
                           extraction_response=None,
                           validation=SimpleNamespace(needs_review=False, errors=[]),
                           processing_time_ms=1, error="")


def _set_status(db_url, job_id, status):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.models import ExtractionJob
    s = sessionmaker(bind=create_engine(db_url))()
    s.get(ExtractionJob, job_id).status = status
    s.commit()
    s.close()


@pytest.fixture
def worker(monkeypatch, _db_url, tmp_path):
    """Run the real job thread over local files with a stubbed engine."""
    import orchestrator
    import app.core.storage as st
    from app.api.routes import extract as ex
    svc = st.StorageService()
    monkeypatch.setattr(orchestrator, "Orchestrator",
                        lambda client_schema_path: SimpleNamespace())
    monkeypatch.setattr(ex, "get_storage", lambda: svc)
    monkeypatch.setattr(ex.settings, "RATE_LIMIT_DELAY", 0)

    def run(job, names, fake):
        keys = [svc.save_upload(b"%PDF-1.7", n, job.id, client_id=job.client_id)[0]
                for n in names]
        monkeypatch.setattr(ex, "_extract_with_template", fake)
        ex._run_extraction_sync(job.id, keys, str(tmp_path / "s.yaml"), _db_url,
                                {"layout": {"cells": {}}}, str(bs.REPO_DIR),
                                str(bs.BACKEND_DIR), str(bs.ENGINE_DIR),
                                original_filenames=names)
    return run


def _rows(db, job_id):
    from app.models.models import DocumentResult
    db.expire_all()
    return sorted(((d.original_filename or d.filename), d.document_type,
                   d.extraction_json is not None)
                  for d in db.query(DocumentResult).filter(DocumentResult.job_id == job_id))


class TestCancelMidBatch:
    def test_finished_files_kept_in_flight_discarded_rest_listed(
            self, db, users, worker, _db_url):
        from app.models.models import ExtractionJob
        job = _job(db, users["acme2"], status="pending", n=4)
        seen = []

        def fake(_o, path, *a, **k):
            seen.append(Path(path).name)
            if len(seen) == 2:          # cancelled while file 2 is read
                _set_status(_db_url, job.id, "cancelled")
            return [_ok(Path(path).name)]

        worker(job, ["a.pdf", "b.pdf", "c.pdf", "d.pdf"], fake)
        assert seen == ["a.pdf", "b.pdf"]                  # c, d never started
        assert _rows(db, job.id) == [("a.pdf", "cheque", True),
                                     ("b.pdf", "cancelled", False),
                                     ("c.pdf", "cancelled", False),
                                     ("d.pdf", "cancelled", False)]
        db.expire_all()
        j = db.get(ExtractionJob, job.id)
        assert j.status == "cancelled" and j.successful == 1
        assert "Cancelled after 1 of 4" in j.progress_message

    def test_a_cancel_between_pages_stops_the_document(self, db, users, worker,
                                                      _db_url):
        """The engine's checkpoint raises inside the document; the thread
        treats it as a cancel, not as a failed document."""
        from cancellation import checkpoint
        job = _job(db, users["acme2"], status="pending", n=2)

        def fake(_o, path, *a, **k):
            _set_status(_db_url, job.id, "cancelled")
            import app.api.routes.extract as ex
            ex.CANCEL_POLL_SEC = 0
            try:
                checkpoint()            # what the preprocessor does per page
            finally:
                ex.CANCEL_POLL_SEC = 1.0
            raise AssertionError("checkpoint did not stop the document")

        worker(job, ["a.pdf", "b.pdf"], fake)
        assert _rows(db, job.id) == [("a.pdf", "cancelled", False),
                                     ("b.pdf", "cancelled", False)]

    def test_cancelled_while_pending_runs_nothing(self, db, users, worker):
        from app.models.models import ExtractionJob
        job = _job(db, users["acme2"], status="cancelled", n=2)
        seen = []
        worker(job, ["a.pdf", "b.pdf"], lambda *a, **k: seen.append(1) or [])
        assert seen == []
        assert [r[1] for r in _rows(db, job.id)] == ["cancelled", "cancelled"]
        db.expire_all()
        assert db.get(ExtractionJob, job.id).status == "cancelled"

    def test_no_cancel_no_change(self, db, users, worker):
        from app.models.models import ExtractionJob
        job = _job(db, users["acme2"], status="pending", n=2)
        worker(job, ["a.pdf", "b.pdf"], lambda _o, p, *a, **k: [_ok(Path(p).name)])
        db.expire_all()
        assert db.get(ExtractionJob, job.id).status == "completed"
        assert [r[1] for r in _rows(db, job.id)] == ["cheque", "cheque"]


class TestCancelRoute:
    def test_owner_cancels_with_a_visible_reason(self, client, auth, db, users):
        job = _job(db, users["acme2"])
        r = client.delete(f"/api/jobs/{job.id}", headers=auth["acme2"])
        assert r.status_code == 200 and r.json()["already_cancelled"] is False
        g = client.get(f"/api/jobs/{job.id}", headers=auth["acme2"]).json()
        assert g["status"] == "cancelled"
        assert g["status_reason"].startswith("Cancelled by its owner")

    def test_cancel_twice(self, client, auth, db, users):
        job = _job(db, users["acme2"])
        client.delete(f"/api/jobs/{job.id}", headers=auth["acme"])
        r = client.delete(f"/api/jobs/{job.id}", headers=auth["acme"])
        assert r.status_code == 200 and r.json()["already_cancelled"] is True
        assert "administrator" in r.json()["status_reason"]

    def test_another_firms_job_is_404(self, client, auth, db, users):
        from app.models.models import ExtractionJob
        job = _job(db, users["other"], cid="other_002")
        r = client.delete(f"/api/jobs/{job.id}", headers=auth["acme"])
        assert r.status_code == 404 and r.json() == {"detail": "Job not found"}
        db.expire_all()
        assert db.get(ExtractionJob, job.id).status == "processing"

    def test_a_finished_job_cannot_be_cancelled(self, client, auth, db, users):
        job = _job(db, users["acme2"], status="completed")
        assert client.delete(f"/api/jobs/{job.id}",
                             headers=auth["acme2"]).status_code == 400


class TestRestartRecovery:
    def test_running_jobs_fail_with_the_reason_and_nothing_is_deleted(
            self, app, db, users, monkeypatch):
        import app.models as models
        from app import main
        from app.models.models import DocumentResult, ExtractionJob
        monkeypatch.setattr(models, "SessionLocal", app.state._sessionmaker)
        running = _job(db, users["acme2"], status="processing")
        pending = _job(db, users["acme2"], status="pending")
        done = _job(db, users["acme2"], status="completed")
        db.add(DocumentResult(job_id=done.id, filename="x.pdf", extraction_json="{}"))
        db.commit()
        main._release_stranded_jobs()
        db.expire_all()
        for j in (running, pending):
            j = db.get(ExtractionJob, j.id)
            assert j.status == "failed" and j.status_reason == "Interrupted by restart"
            assert "restart" in j.error_message
        assert db.get(ExtractionJob, done.id).status == "completed"
        assert db.query(DocumentResult).filter(DocumentResult.job_id == done.id).count() == 1
