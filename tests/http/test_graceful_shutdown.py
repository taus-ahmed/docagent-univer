"""Graceful shutdown on SIGTERM (Part 2.3), with a simulated signal."""
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.http.test_job_cancel import _job, _ok, _rows, worker  # noqa: E402,F401


@pytest.fixture(autouse=True)
def not_draining():
    from app.core import lifecycle
    lifecycle.reset()
    yield
    lifecycle.reset()


def test_the_file_in_progress_finishes_and_the_rest_are_marked(db, users, worker):
    from app.core import lifecycle
    from app.models.models import ExtractionJob
    job = _job(db, users["acme2"], status="pending", n=3)

    def fake(_o, path, *a, **k):
        lifecycle.begin_drain()               # SIGTERM arrives while file 1 is read
        return [_ok(Path(path).name)]
    worker(job, ["a.pdf", "b.pdf", "c.pdf"], fake)
    assert _rows(db, job.id) == [("a.pdf", "cheque", True),
                                 ("b.pdf", "interrupted", False),
                                 ("c.pdf", "interrupted", False)]
    db.expire_all()
    j = db.get(ExtractionJob, job.id)
    assert j.status == "failed" and j.status_reason == "Interrupted by restart"
    assert "1 of 3 file(s) had been read and are kept" in j.error_message
    assert lifecycle.active_jobs() == set()


def test_new_jobs_are_refused_while_draining(client, auth):
    from app.core import lifecycle
    lifecycle.begin_drain()
    r = client.post("/api/extract/upload", headers=auth["acme2"],
                    files={"files": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 503 and r.headers.get("retry-after") == "60"
    assert "restarting" in r.json()["detail"]


def test_shutdown_waits_for_running_jobs_but_not_forever():
    import threading
    import time
    from app.core import lifecycle
    lifecycle.job_started(99)
    threading.Timer(0.3, lambda: lifecycle.job_finished(99)).start()
    t0 = time.monotonic()
    assert lifecycle.wait_for_jobs(5) == set() and time.monotonic() - t0 < 2
    lifecycle.job_started(100)
    assert lifecycle.wait_for_jobs(0.2) == {100}
    lifecycle.job_finished(100)


def test_the_app_shutdown_drains(app):
    """The lifespan's shutdown sets the drain (TestClient exit = SIGTERM path)."""
    from fastapi.testclient import TestClient
    from app.core import lifecycle
    with TestClient(app):
        assert not lifecycle.draining()
    assert lifecycle.draining()
