"""Review-3 F11: a BaseException in extraction never strands a job.

In Codex's run the batch end-to-end test waited out its full 600 s: the
replay cache raises `ReplayEnvironmentError` — a BaseException on purpose —
when the machine has no Poppler (the page-image fingerprint cannot be made),
and the worker caught only `Exception`. The thread died and the job row stayed
`processing` for ever. Production never replays, but SystemExit and
KeyboardInterrupt take the same route.

Each BaseException is forced from inside extraction: the job must end
`failed` with a named reason, the temp copies must be released, and the
exception must still propagate (the thread is going down for a reason).
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.harness.llm_cache import ReplayEnvironmentError  # noqa: E402
from tests.http.test_temp_copy_cleanup import (  # noqa: E402
    _copies, _job, _ok, _run_worker, s3,  # noqa: F401  (s3 is a fixture)
)


class _Stop(BaseException):
    """A BaseException nobody else defines."""


@pytest.mark.parametrize("exc", [SystemExit(3), KeyboardInterrupt(),
                                 ReplayEnvironmentError("no Poppler"), _Stop()],
                         ids=lambda e: type(e).__name__)
def test_a_base_exception_fails_the_job_with_a_named_reason(
        exc, s3, db, users, _db_url, monkeypatch):
    import orchestrator
    from app.api.routes import extract as extract_mod
    from app.models.models import ExtractionJob

    job = _job(db, users)
    s3.save_schema("client_id: acme_001\n", "acme_001")
    keys = [s3.save_upload(b"%PDF-1.7", f"{n}.pdf", job.id, client_id="acme_001")[0]
            for n in ("first", "dies")]
    schema_path = s3.get_schema_path("acme_001")
    seen = []

    def fake(_orch, path, *a, **k):
        seen.append(Path(path))
        if len(seen) == 2:
            raise exc
        return [_ok(Path(path).name)]

    monkeypatch.setattr(orchestrator, "Orchestrator", lambda client_schema_path: SimpleNamespace())
    monkeypatch.setattr("app.services.job_worker.get_storage", lambda: s3)
    monkeypatch.setattr("app.services.job_worker._extract_with_template", fake)
    monkeypatch.setattr(extract_mod.settings, "RATE_LIMIT_DELAY", 0)

    with pytest.raises(type(exc)):
        _run_worker(extract_mod, s3, job, keys, schema_path, _db_url)

    db.expire_all()
    j = db.get(ExtractionJob, job.id)
    assert j.status == "failed", j.status
    assert j.error_message.startswith("Interrupted") and type(exc).__name__ in j.error_message
    assert "no Poppler" not in j.error_message            # the type, never the message
    assert j.marks().get("status_reason") == "Interrupted"
    assert j.completed_at is not None
    assert _copies(s3) == [], "a temp copy survived the interrupted job"


def test_a_job_already_cancelled_is_left_cancelled(s3, db, users, _db_url, monkeypatch):
    import orchestrator
    from app.api.routes import extract as extract_mod
    from app.models.models import ExtractionJob
    from app.services.job_worker import _fail_interrupted_job
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    job = _job(db, users)
    job.status = "cancelled"
    db.commit()
    _fail_interrupted_job(sessionmaker(bind=create_engine(_db_url)), job.id, SystemExit())
    db.expire_all()
    assert db.get(ExtractionJob, job.id).status == "cancelled"


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), SystemExit(4)],
                         ids=lambda e: type(e).__name__)
def test_a_base_exception_while_the_engine_is_created_fails_the_job(
        exc, s3, db, users, _db_url, monkeypatch):
    """Recheck R7: the job thread's own database engine is created before the
    main try; a BaseException there (`job_worker.py` "DB session failed")
    went past `except Exception` and the job stayed `pending`."""
    import sqlalchemy
    from app.api.routes import extract as extract_mod
    from app.models.models import ExtractionJob

    job = _job(db, users)
    s3.save_schema("client_id: acme_001\n", "acme_001")
    keys = [s3.save_upload(b"%PDF-1.7", "a.pdf", job.id, client_id="acme_001")[0]]
    real, calls = sqlalchemy.create_engine, []

    def first_call_dies(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise exc
        return real(*a, **k)

    monkeypatch.setattr(sqlalchemy, "create_engine", first_call_dies)
    monkeypatch.setattr("app.services.job_worker.get_storage", lambda: s3)
    with pytest.raises(type(exc)):
        _run_worker(extract_mod, s3, job, keys, s3.get_schema_path("acme_001"), _db_url)
    db.expire_all()
    j = db.get(ExtractionJob, job.id)
    assert j.status == "failed" and j.error_message.startswith("Interrupted"), (j.status, j.error_message)
    assert type(exc).__name__ in j.error_message
