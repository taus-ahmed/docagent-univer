"""Temp copies of client files are always deleted (round 12 A2).

With the object store, `storage.get_local_path` fetches a client's document
(or schema) to a temp file because pdfplumber wants a path, and nothing ever
deleted it: every processed document stayed on the server's disk. Now:

  * copies go to the app's OWN directory (`storage.temp_dir`);
  * `release()` deletes a copy and NOTHING else (never the local store's file);
  * every caller releases on success, failure and cancel;
  * boot sweeps copies older than a day, from that directory only.
"""
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.test_storage import FakeS3, _settings  # noqa: E402


@pytest.fixture
def s3(monkeypatch, tmp_path):
    from app.core.storage import StorageService
    st = _settings()
    monkeypatch.setattr(st, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(st, "S3_BUCKET", "docagent-test")
    fake = FakeS3()
    svc = StorageService()
    monkeypatch.setattr(svc, "_s3", lambda: fake)
    svc.temp_dir = tmp_path / "copies"
    return svc


def _copies(svc):
    d = Path(svc.temp_dir)
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# ── the storage primitives ───────────────────────────────────────────────────

class TestStorage:
    def test_a_copy_lands_in_the_apps_own_directory(self, s3):
        key, _ = s3.save_upload(b"%PDF-1.7", "a.pdf", 1, client_id="acme")
        path = s3.get_local_path(key)
        assert path.parent.resolve() == Path(s3.temp_dir).resolve()
        assert s3.is_temp_copy(path)

    def test_release_deletes_the_copy(self, s3):
        key, _ = s3.save_upload(b"x", "a.pdf", 1, client_id="acme")
        path = s3.get_local_path(key)
        s3.release(path)
        assert not path.exists() and _copies(s3) == []

    def test_local_copy_releases_on_an_exception(self, s3):
        key, _ = s3.save_upload(b"x", "a.pdf", 1, client_id="acme")
        with pytest.raises(RuntimeError):
            with s3.local_copy(key) as path:
                assert path.exists()
                raise RuntimeError("extraction failed")
        assert _copies(s3) == []

    def test_release_never_deletes_the_local_stores_file(self, tmp_path, monkeypatch):
        from app.core.storage import StorageService
        st = _settings()
        monkeypatch.setattr(st, "LOCAL_UPLOAD_DIR", tmp_path / "st" / "uploads")
        monkeypatch.setattr(st, "LOCAL_OUTPUT_DIR", tmp_path / "st" / "outputs")
        monkeypatch.setattr(st, "LOCAL_SCHEMAS_DIR", tmp_path / "st" / "schemas")
        monkeypatch.setattr(st, "STORAGE_BACKEND", "local")
        svc = StorageService()
        key, _ = svc.save_upload(b"x", "a.pdf", 1, client_id="acme")
        path = svc.get_local_path(key)
        svc.release(path)
        with svc.local_copy(key) as p2:
            assert p2 == path
        assert path.exists(), "the stored original was deleted"

    def test_release_ignores_a_lookalike_outside_the_directory(self, s3, tmp_path):
        outside = tmp_path / "copy-elsewhere.pdf"
        outside.write_bytes(b"x")
        s3.release(outside)
        s3.release(None)
        assert outside.exists()


class TestSweep:
    def test_only_stale_copies_in_the_directory_go(self, s3, tmp_path):
        d = Path(s3.temp_dir)
        d.mkdir(parents=True)
        old, fresh = d / "copy-old.pdf", d / "copy-fresh.pdf"
        foreign = d / "not-ours.pdf"          # no prefix: not ours to delete
        sub = d / "copy-subdir"
        outside = tmp_path / "copy-outside.pdf"
        for f in (old, fresh, foreign, outside):
            f.write_bytes(b"x")
        sub.mkdir()
        (sub / "copy-inner.pdf").write_bytes(b"x")
        two_days = time.time() - 2 * 86400
        for f in (old, foreign, outside, sub / "copy-inner.pdf"):
            os.utime(f, (two_days, two_days))
        assert s3.sweep_temp_copies() == 1
        assert not old.exists()
        assert fresh.exists() and foreign.exists() and outside.exists()
        assert (sub / "copy-inner.pdf").exists()

    def test_a_missing_directory_is_zero(self, s3):
        assert s3.sweep_temp_copies() == 0

    def test_boot_runs_the_sweep(self):
        src = (bs.BACKEND_DIR / "app" / "main.py").read_text(encoding="utf-8")
        assert "sweep_temp_copies(" in src


# ── every caller ─────────────────────────────────────────────────────────────

def _job(db, users):
    from app.models.models import ExtractionJob
    j = ExtractionJob(user_id=users["acme"].id, client_id="acme_001",
                      status="pending", total_docs=3, input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    return j


def _ok(name):
    return SimpleNamespace(filename=name, document_type="cheque", success=True,
                           extracted_data={"needs_review": False, "validation": {}},
                           extraction_response=None,
                           validation=SimpleNamespace(needs_review=False, errors=[]),
                           processing_time_ms=1, error="")


def _run_worker(extract_mod, s3, job, keys, schema_path, db_url):
    extract_mod._run_extraction_sync(
        job.id, keys, str(schema_path), db_url, {"layout": {"cells": {}}},
        str(bs.REPO_DIR), str(bs.BACKEND_DIR), str(bs.ENGINE_DIR))


class TestWorker:
    def test_success_failure_and_cancel_leave_no_copy(self, s3, db, users, _db_url,
                                                     monkeypatch):
        import orchestrator
        from app.api.routes import extract as extract_mod
        from app.models.models import ExtractionJob

        job = _job(db, users)
        s3.save_schema("client_id: acme_001\n", "acme_001")
        keys = [s3.save_upload(b"%PDF-1.7", f"{n}.pdf", job.id, client_id="acme_001")[0]
                for n in ("ok", "boom", "cancelled")]
        schema_path = s3.get_schema_path("acme_001")
        assert _copies(s3)

        seen = []

        def fake(_orch, path, *a, **k):
            seen.append(Path(path))
            assert Path(path).exists()
            n = len(seen)
            if n == 2:
                raise RuntimeError("engine blew up")
            if n == 3:   # the user cancels while this document runs
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker
                s = sessionmaker(bind=create_engine(_db_url))()
                s.get(ExtractionJob, job.id).status = "cancelled"
                s.commit()
                s.close()
            return [_ok(Path(path).name)]

        monkeypatch.setattr(orchestrator, "Orchestrator", lambda client_schema_path: SimpleNamespace())
        monkeypatch.setattr("app.services.job_worker.get_storage", lambda: s3)
        monkeypatch.setattr("app.services.job_worker._extract_with_template", fake)
        monkeypatch.setattr(extract_mod.settings, "RATE_LIMIT_DELAY", 0)
        _run_worker(extract_mod, s3, job, keys, schema_path, _db_url)

        assert len(seen) == 3 and all(s3.is_temp_copy(p) for p in seen)
        assert _copies(s3) == [], "a temp copy of a client file survived the job"

    def test_a_worker_that_fails_before_any_document_still_releases_the_schema(
            self, s3, db, users, _db_url, monkeypatch):
        import orchestrator
        from app.api.routes import extract as extract_mod

        job = _job(db, users)
        s3.save_schema("client_id: acme_001\n", "acme_001")
        schema_path = s3.get_schema_path("acme_001")

        def broken(client_schema_path):
            raise RuntimeError("schema unreadable")

        monkeypatch.setattr(orchestrator, "Orchestrator", broken)
        monkeypatch.setattr("app.services.job_worker.get_storage", lambda: s3)
        _run_worker(extract_mod, s3, job, [], schema_path, _db_url)
        assert _copies(s3) == []


class TestRoutes:
    @pytest.fixture
    def with_s3(self, app, s3):
        from app.core.storage import get_storage
        app.dependency_overrides[get_storage] = lambda: s3
        s3.save_schema("client_id: acme_001\n", "acme_001")
        yield s3
        app.dependency_overrides.pop(get_storage, None)

    def test_an_upload_refused_after_the_schema_copy_leaves_none(
            self, client, auth, with_s3, pdf_bytes):
        r = client.post("/api/extract/upload", headers=auth["acme"],
                        data={"client_id": "acme_001", "template_id": "987654"},
                        files={"files": ("a.pdf", pdf_bytes, "application/pdf")})
        assert r.status_code == 404, r.text
        assert _copies(with_s3) == []

    def test_adding_a_watch_folder_leaves_no_copy(self, client, auth, with_s3, db):
        from app.models.models import WatchFolder
        r = client.post("/api/watch", headers=auth["acme"],
                        json={"folder_id": "tmpcopy-1", "folder_name": "f",
                              "client_id": "acme_001"})
        assert r.status_code == 201, r.text
        assert _copies(with_s3) == []
        db.delete(db.get(WatchFolder, r.json()["id"]))
        db.commit()
