"""Run Q, UI1 — POST /api/jobs/{id}/rerun: the same files, a NEW job.

The finished job, its results and its download are never touched; the new job
goes through the ordinary upload path with the template asked for (or none).
"""
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture(autouse=True)
def _no_real_extraction(monkeypatch):
    import threading
    started = []

    class _Inert(threading.Thread):
        def start(self):
            started.append(self)

    monkeypatch.setattr("app.api.routes.extract.threading.Thread", _Inert)
    return started


@pytest.fixture
def local(monkeypatch):
    import app.core.storage as st
    svc = st.StorageService()
    monkeypatch.setattr(st, "_storage", svc)
    return svc


def _finished_job(db, owner, cid, storage, pdf_bytes):
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=owner.id, client_id=cid, status="completed", total_docs=1,
                      successful=1, input_source="upload", schema_id=None)
    db.add(j)
    db.commit()
    db.refresh(j)
    key, _ = storage.save_upload(pdf_bytes, "inv.pdf", j.id, client_id=cid)
    db.add(DocumentResult(job_id=j.id, filename="inv.pdf", original_filename="inv.pdf",
                          s3_key=key, extraction_json=json.dumps(
                              {"extracted_fields": {"B1": "INV-1"}})))
    db.commit()
    return j


def test_rerun_starts_a_new_job_and_leaves_the_old_one(client, auth, db, users, local,
                                                       pdf_bytes, templates,
                                                       _no_real_extraction):
    from app.models.models import DocumentResult, ExtractionJob
    j = _finished_job(db, users["acme2"], "acme_001", local, pdf_bytes)
    before = [(d.id, d.extraction_json) for d in
              db.query(DocumentResult).filter(DocumentResult.job_id == j.id)]
    tid = templates["acme_private"].id if "acme_private" in templates else None
    r = client.post(f"/api/jobs/{j.id}/rerun", headers=auth["acme"],
                    json={"template_id": tid})
    assert r.status_code == 202, r.text
    new_id = r.json()["job_id"]
    assert new_id != j.id
    db.expire_all()
    new = db.get(ExtractionJob, new_id)
    assert new.client_id == "acme_001" and new.total_docs == 1
    assert new.schema_id == (str(tid) if tid else None)
    old = db.get(ExtractionJob, j.id)
    assert old.status == "completed"
    assert [(d.id, d.extraction_json) for d in
            db.query(DocumentResult).filter(DocumentResult.job_id == j.id)] == before
    assert len(_no_real_extraction) == 1
    # the new job's copy of the file lives under the NEW job's prefix
    assert local.exists(local.upload_key("acme_001", new_id, "inv.pdf"))


def test_rerun_with_no_template(client, auth, db, users, local, pdf_bytes):
    from app.models.models import ExtractionJob
    j = _finished_job(db, users["acme2"], "acme_001", local, pdf_bytes)
    r = client.post(f"/api/jobs/{j.id}/rerun", headers=auth["acme"], json={"template_id": None})
    assert r.status_code == 202, r.text
    db.expire_all()
    assert db.get(ExtractionJob, r.json()["job_id"]).schema_id is None


def test_rerun_of_a_job_whose_files_are_gone_says_so(client, auth, db, users, local,
                                                     pdf_bytes):
    from app.models.models import DocumentResult
    j = _finished_job(db, users["acme2"], "acme_001", local, pdf_bytes)
    for d in db.query(DocumentResult).filter(DocumentResult.job_id == j.id):
        local.delete(d.s3_key)
    r = client.post(f"/api/jobs/{j.id}/rerun", headers=auth["acme"], json={})
    assert r.status_code == 409 and "no longer stored" in r.json()["detail"]


def test_another_firms_job_answers_like_a_missing_one(client, auth, db, users, local,
                                                      pdf_bytes):
    j = _finished_job(db, users["other"], "other_002", local, pdf_bytes)
    r = client.post(f"/api/jobs/{j.id}/rerun", headers=auth["acme"], json={})
    miss = client.post("/api/jobs/987654321/rerun", headers=auth["acme"], json={})
    assert r.status_code == 404 and r.json() == miss.json()
