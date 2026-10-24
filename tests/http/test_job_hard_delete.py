"""
Hard delete of a job: DELETE /api/jobs/{id}/data (docs/proposals/retention.md).

Removes the job's stored files (sources and outputs, local or object store),
the page readings the review screen keeps in memory (page and OCR images) with
their temp copies, and every result row; keeps the job record (id, owner,
timestamps, counts) with a `deleted` mark so history still adds up. A tenant
admin of the job's firm or a platform admin may do it; nobody else; another
firm's job answers 404; a second delete is a no-op that says so.
"""
import json
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.test_storage import FakeS3, _settings  # noqa: E402


def _make_job(db, owner, cid, storage, n_docs=2, status="completed"):
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=owner.id, client_id=cid, status=status,
                      total_docs=n_docs, successful=n_docs, input_source="upload",
                      progress_message="Done: a.pdf", error_message="a.pdf: x")
    db.add(j)
    db.commit()
    db.refresh(j)
    for k in range(n_docs):
        name = f"doc{k}.pdf"
        key, _ = storage.save_upload(b"%PDF-1.4 secret " + name.encode(), name,
                                     j.id, client_id=cid)
        db.add(DocumentResult(job_id=j.id, filename=name, original_filename=name,
                              s3_key=key, raw_llm_response="model said secret",
                              extraction_json=json.dumps({"extracted_fields": {"B1": "secret"}})))
    storage.put(storage.output_key(cid, j.id, "out.xlsx"), b"PK secret")
    db.commit()
    return j


@pytest.fixture
def local(monkeypatch):
    import app.core.storage as st
    svc = st.StorageService()
    monkeypatch.setattr(st, "_storage", svc)
    return svc


@pytest.fixture
def r2(monkeypatch, tmp_path):
    import app.core.storage as st
    s = _settings()
    monkeypatch.setattr(s, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(s, "S3_BUCKET", "docagent-test")
    fake = FakeS3()
    svc = st.StorageService()
    monkeypatch.setattr(svc, "_s3", lambda: fake)
    svc.temp_dir = tmp_path / "copies"
    svc._fake = fake
    monkeypatch.setattr(st, "_storage", svc)
    return svc


def _keys_under(svc, prefix):
    if svc.backend == "s3":
        return [k for (_b, k) in svc._fake.objects if k.startswith(prefix + "/")]
    d = svc._local_path(prefix)
    return [p for p in d.rglob("*") if p.is_file()] if d.exists() else []


@pytest.mark.parametrize("backend", ["local", "r2"])
def test_delete_removes_files_results_and_content(client, auth, db, users,
                                                 backend, request):
    from app.models.models import DocumentResult, ExtractionJob
    svc = request.getfixturevalue(backend)
    j = _make_job(db, users["acme2"], "acme_001", svc)
    prefix = svc.job_prefix("acme_001", j.id)
    assert len(_keys_under(svc, prefix)) == 3

    r = client.delete(f"/api/jobs/{j.id}/data", headers=auth["acme"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files_deleted"] == 3 and body["results_deleted"] == 2
    assert body["already_deleted"] is False

    assert _keys_under(svc, prefix) == []
    db.expire_all()
    assert db.query(DocumentResult).filter(DocumentResult.job_id == j.id).count() == 0
    job = db.get(ExtractionJob, j.id)
    assert job is not None                                # the record stays
    assert (job.total_docs, job.successful, job.user_id) == (2, 2, users["acme2"].id)
    assert job.deleted_at and job.progress_message is None and job.error_message is None
    assert "secret" not in json.dumps({c.name: str(getattr(job, c.name))
                                       for c in job.__table__.columns})

    g = client.get(f"/api/jobs/{j.id}", headers=auth["acme"]).json()
    assert g["deleted_at"] == job.deleted_at
    assert client.get(f"/api/jobs/{j.id}/results", headers=auth["acme"]).json() == []


def test_a_second_delete_is_a_no_op_that_says_so(client, auth, db, users, local):
    j = _make_job(db, users["acme2"], "acme_001", local)
    first = client.delete(f"/api/jobs/{j.id}/data", headers=auth["acme"]).json()
    r = client.delete(f"/api/jobs/{j.id}/data", headers=auth["acme"])
    assert r.status_code == 200, r.text
    assert r.json()["already_deleted"] is True
    assert r.json()["files_deleted"] == 0 and r.json()["results_deleted"] == 0
    assert r.json()["deleted_at"] == first["deleted_at"]


def test_another_firms_job_is_404_and_untouched(client, auth, db, users, local):
    from app.models.models import DocumentResult
    j = _make_job(db, users["other"], "other_002", local)
    r = client.delete(f"/api/jobs/{j.id}/data", headers=auth["acme"])
    missing = client.delete("/api/jobs/987654321/data", headers=auth["acme"])
    assert r.status_code == 404 and r.json() == missing.json()
    assert len(_keys_under(local, local.job_prefix("other_002", j.id))) == 3
    db.expire_all()
    assert db.query(DocumentResult).filter(DocumentResult.job_id == j.id).count() == 2


@pytest.mark.parametrize("who", ["acme2", "rev"])
def test_the_owner_and_a_reviewer_may_not_hard_delete(client, auth, db, users,
                                                      local, who):
    from tests.http.conftest import _mkuser
    from app.core.auth import create_access_token
    u = users.get(who) or _mkuser(db, "acme_reviewer", "reviewer", "acme_001")
    h = {"Authorization": "Bearer " + create_access_token(
        {"sub": str(u.id), "role": u.role, "client_id": u.client_id})}
    j = _make_job(db, users["acme2"], "acme_001", local)
    assert client.delete(f"/api/jobs/{j.id}/data", headers=h).status_code == 403
    assert len(_keys_under(local, local.job_prefix("acme_001", j.id))) == 3


def test_a_platform_admin_may_delete_any_firms_job(client, auth, db, users, local):
    j = _make_job(db, users["other"], "other_002", local)
    assert client.delete(f"/api/jobs/{j.id}/data",
                         headers=auth["super"]).status_code == 200
    assert _keys_under(local, local.job_prefix("other_002", j.id)) == []


def test_a_running_job_must_be_cancelled_first(client, auth, db, users, local):
    j = _make_job(db, users["acme2"], "acme_001", local, status="processing")
    r = client.delete(f"/api/jobs/{j.id}/data", headers=auth["acme"])
    assert r.status_code == 409, r.text
    assert len(_keys_under(local, local.job_prefix("acme_001", j.id))) == 3


def test_the_review_screens_readings_and_temp_copies_go(client, auth, db, users, r2):
    """A page reading cached for the review screen holds the page and OCR
    images in memory and, on the object store, a temp copy on disk."""
    from app.api.routes import review
    j = _make_job(db, users["acme2"], "acme_001", r2, n_docs=1)
    from app.models.models import DocumentResult
    d = db.query(DocumentResult).filter(DocumentResult.job_id == j.id).first()
    copy = r2.get_local_path(d.s3_key)
    with review._cache_lock:
        review._cache[d.s3_key] = {"path": str(copy), "ocr_images": {1: "img"}}
    assert client.delete(f"/api/jobs/{j.id}/data", headers=auth["acme"]).status_code == 200
    assert d.s3_key not in review._cache
    assert not Path(copy).exists()


def test_the_log_names_ids_and_counts_only(client, auth, db, users, local, capfd):
    j = _make_job(db, users["acme2"], "acme_001", local)
    capfd.readouterr()
    client.delete(f"/api/jobs/{j.id}/data", headers=auth["acme"])
    out = "".join(capfd.readouterr())
    assert f"job {j.id}" in out
    assert "doc0" not in out and "secret" not in out and "acme_001" not in out
