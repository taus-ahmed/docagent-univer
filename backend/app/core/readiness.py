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

import concurrent.futures
import uuid

#: seconds a single readiness check may take
CHECK_TIMEOUT = 5.0


def _bounded(fn):
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(fn).result(timeout=CHECK_TIMEOUT)
    except concurrent.futures.TimeoutError:
        return "fail:timeout"
    except Exception as e:
        return f"fail:{type(e).__name__}"
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


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
