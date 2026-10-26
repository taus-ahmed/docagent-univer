"""Password-protected PDFs (Part 1.7).

A per-file password comes with the upload and lives only in memory: it is
never written to disk, stored, logged or returned. A wrong or missing one is
a named failure of THAT file; the batch carries on. Owner-password-only PDFs
open as before.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.http.test_job_cancel import _job, _ok  # noqa: E402

SECRET = "QZXPW-Sentinel-77"


def _pdf(user=None, owner=None, text="Invoice 42"):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(300, 300)
    if user is not None or owner is not None:
        w.encrypt(user_password=user or "", owner_password=owner or "owner-only")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_upload_accepts_a_locked_pdf_and_refuses_bad_passwords_without_echo(client, auth):
    files = [("files", ("locked.pdf", _pdf(user=SECRET), "application/pdf"))]
    r = client.post("/api/extract/upload", headers=auth["acme2"], files=files,
                    data={"passwords": json.dumps(["not-json-safe-" + SECRET, None, None])})
    assert r.status_code == 400 and SECRET not in r.text
    r = client.post("/api/extract/upload", headers=auth["acme2"], files=files,
                    data={"passwords": "{" + SECRET})
    assert r.status_code == 400 and SECRET not in r.text


def test_validation_counts_pages_with_the_password_in_memory():
    from app.services.uploads import _validate_upload_content
    locked = _pdf(user=SECRET)
    assert _validate_upload_content("a.pdf", locked, SECRET)[2] == 1
    assert _validate_upload_content("a.pdf", locked)[2] == 1          # unknown: 1
    assert _validate_upload_content("o.pdf", _pdf(owner="o"))[1] == "pdf"


@pytest.fixture
def run(monkeypatch, _db_url, tmp_path):
    import orchestrator
    import app.core.storage as st
    from app.api.routes import extract as ex
    svc = st.StorageService()
    monkeypatch.setattr(orchestrator, "Orchestrator",
                        lambda client_schema_path: SimpleNamespace())
    monkeypatch.setattr("app.services.job_worker.get_storage", lambda: svc)
    monkeypatch.setattr(ex.settings, "RATE_LIMIT_DELAY", 0)
    seen = {}

    def fake(_o, path, *a, **k):
        from pdf_password import pdf_lock_state
        seen[Path(path).name] = pdf_lock_state(path)
        return [_ok(Path(path).name)]
    monkeypatch.setattr("app.services.job_worker._extract_with_template", fake)

    def go(job, items):
        keys = [svc.save_upload(content, name, job.id, client_id=job.client_id)[0]
                for name, content, _pw in items]
        ex._run_extraction_sync(job.id, keys, str(tmp_path / "s.yaml"), _db_url,
                                {"layout": {"cells": {}}}, str(bs.REPO_DIR),
                                str(bs.BACKEND_DIR), str(bs.ENGINE_DIR),
                                original_filenames=[n for n, _c, _p in items],
                                passwords=[pw for _n, _c, pw in items])
        return svc, seen
    return go


def test_each_file_succeeds_or_fails_by_name_and_the_password_leaves_no_trace(
        run, db, users, capfd, caplog):
    from app.models.models import DocumentResult, ExtractionJob
    caplog.set_level(logging.DEBUG)
    job = _job(db, users["acme2"], status="pending", n=4)
    import app.core.storage as st
    tmp = Path(st.StorageService().temp_dir)
    before = set(tmp.glob("copy-*")) if tmp.exists() else set()
    svc, seen = run(job, [("right.pdf", _pdf(user=SECRET), SECRET),
                          ("wrong.pdf", _pdf(user=SECRET), "nope"),
                          ("none.pdf", _pdf(user=SECRET), None),
                          ("plain.pdf", _pdf(), None)])
    db.expire_all()
    rows = {d.original_filename: d for d in
            db.query(DocumentResult).filter(DocumentResult.job_id == job.id)}
    assert rows["right.pdf"].extraction_json is not None
    assert "password incorrect" in rows["wrong.pdf"].validation_errors
    assert "password required" in rows["none.pdf"].validation_errors
    assert rows["plain.pdf"].extraction_json is not None
    # the engine read a DECRYPTED copy, never the locked file
    assert all(state == "open" for state in seen.values()), seen
    j = db.get(ExtractionJob, job.id)
    assert j.successful == 2 and j.failed == 2
    # nowhere: logs, any stored column, any file left behind
    out, err = capfd.readouterr()
    assert SECRET not in out + err + caplog.text
    for d in rows.values():
        for col in ("extraction_json", "validation_errors", "validation_warnings",
                    "raw_llm_response", "filename", "original_filename", "s3_key"):
            assert SECRET not in str(getattr(d, col) or "")
    assert SECRET not in str(j.notes or "") + str(j.error_message or "")
    after = set(tmp.glob("copy-*")) if tmp.exists() else set()
    assert after - before == set(), after - before     # decrypted copies released
