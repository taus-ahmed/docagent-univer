"""Liveness and readiness (Part 2.2).

    /health  the process is up. Nothing else is asked.
    /ready   it can do its job: the database answers, storage takes a write,
             Tesseract and pdftoppm are present and answer within their probe
             deadline, and the boot migrations did not fail.

Each check is bounded by a timeout and answers "ok", "fail" or "skipped" with
at most a short reason code — never an error message, a connection string,
a path or a version: the page is public to the platform's prober.
"""
from __future__ import annotations

import threading
import uuid

#: seconds a single readiness check may take
CHECK_TIMEOUT = 5.0

#: checks whose last probe is still running, by name
_INFLIGHT: dict = {}
_LOCK = threading.Lock()


def _bounded(fn):
    """`fn()` on a DAEMON thread, given CHECK_TIMEOUT seconds.

    Review-3 F9: this used a ThreadPoolExecutor, whose workers are joined at
    interpreter exit — so one probe stuck on a hung dependency (a database
    that accepts the connection and never answers) kept the process from
    exiting, and a deploy's SIGTERM waited on it. A daemon thread is
    abandoned at exit. A probe that is still stuck when the next one arrives
    is not joined by another thread: that check answers `fail:busy`, so a
    prober polling every few seconds cannot pile up threads."""
    name = getattr(fn, "__name__", "check")
    with _LOCK:
        prev = _INFLIGHT.get(name)
        if prev is not None and prev.is_alive():
            return "fail:busy"
    box = {}

    def run():
        try:
            box["v"] = fn()
        except Exception as e:
            box["v"] = f"fail:{type(e).__name__}"

    t = threading.Thread(target=run, name=f"readiness-{name}", daemon=True)
    with _LOCK:
        _INFLIGHT[name] = t
    t.start()
    t.join(CHECK_TIMEOUT)
    if t.is_alive():
        return "fail:timeout"
    return box.get("v", "fail:unknown")


def check_database():
    from sqlalchemy import text
    import app.models as models
    db = models.SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
    return "ok"


def check_storage():
    from app.config import settings
    from app.core.storage import get_storage
    s = get_storage()
    key = f"_ready/{uuid.uuid4().hex}.probe"
    if s.backend == "s3":
        c = s._s3()
        c.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=b"ok")
        c.delete_object(Bucket=settings.S3_BUCKET, Key=key)
        return "ok"
    p = s.root / key
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"ok")
    p.unlink()
    return "ok"


def check_tesseract():
    import external_tools
    external_tools.tesseract_version()
    return "ok"


def check_pdftoppm():
    import external_tools
    external_tools.poppler_version("pdftoppm")
    return "ok"


def check_migrations(application):
    m = getattr(application.state, "migrations", None)
    if m is None:
        return "skipped"
    return "fail:migration" if (m or {}).get("failed") else "ok"


def readiness(application) -> tuple[bool, dict]:
    import importlib
    importlib.import_module("app.services.paths")   # engine on sys.path
    checks = {
        "database": _bounded(check_database),
        "storage": _bounded(check_storage),
        "tesseract": _bounded(check_tesseract),
        "pdftoppm": _bounded(check_pdftoppm),
        "migrations": check_migrations(application),
    }
    ok = all(v in ("ok", "skipped") for v in checks.values())
    return ok, checks
