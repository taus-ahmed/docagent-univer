"""
Two firms at the same moment (A3): every result lands in its own firm and job.

Both firms upload a 50-file batch through the real route at the same instant
(a barrier releases both requests together), and the real job threads run side
by side against the same database. Only the model call is faked: each file's
result carries the name of the file it was read from and the storage path it
was read at, so a result written to the wrong job, or read from another firm's
file, is visible in the row itself.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

FIRMS = ("ccAfirm", "ccBfirm")
N = 50


def _fake_extract(orchestrator, file_path, template_data, selected_pages=None,
                  batch_schemas=None):
    p = Path(file_path)
    time.sleep(0.002)                        # let the two threads interleave
    ed = {"extracted_fields": {"B2": p.name, "B3": p.as_posix()},
          "slot_map": {"fields": [{"ref": "B2", "row_label": "File"},
                                  {"ref": "B3", "row_label": "Path"}], "tables": []},
          "validation": {"confidence_map": {"B2": "high", "B3": "high"},
                         "flagged_fields": []}}
    return [SimpleNamespace(filename=p.name, document_type="invoice", success=True,
                            extracted_data=ed, extraction_response=None,
                            validation=SimpleNamespace(needs_review=False, errors=[]),
                            processing_time_ms=1, error="")]


@pytest.fixture
def worker(monkeypatch, _db_url):
    import orchestrator
    from app.config import settings
    yaml_text = (bs.BACKEND_DIR / "engine" / "demo_accounting.yaml").read_text(encoding="utf-8")
    for f in FIRMS:
        (settings.LOCAL_SCHEMAS_DIR / "clients" / f"{f}.yaml").write_text(
            yaml_text, encoding="utf-8")
    monkeypatch.setattr(settings, "DATABASE_URL", _db_url)
    monkeypatch.setattr(settings, "RATE_LIMIT_DELAY", 0.0)
    monkeypatch.setattr(orchestrator, "Orchestrator",
                        lambda client_schema_path: SimpleNamespace())
    monkeypatch.setattr("app.services.job_worker._extract_with_template", _fake_extract)
    threads = []
    real = threading.Thread

    class _Tracked(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            threads.append(self)
    monkeypatch.setattr("app.api.routes.extract.threading",
                        SimpleNamespace(Thread=_Tracked))
    return threads


def _hdr(db, firm):
    from app.core.auth import create_access_token
    from tests.http.conftest import _mkuser
    u = _mkuser(db, f"{firm}_user", "client", firm)
    tok = create_access_token({"sub": str(u.id), "role": u.role, "client_id": firm})
    return {"Authorization": f"Bearer {tok}"}


def test_two_firms_fifty_files_each_at_the_same_moment(client, db, worker):
    from app.models.models import DocumentResult, ExtractionJob
    pdf = (bs.PDF_DIR / "INV-2024-0031.pdf").read_bytes()
    hdrs = {f: _hdr(db, f) for f in FIRMS}
    db.commit()
    barrier = threading.Barrier(len(FIRMS))
    answers, errors = {}, []

    def upload(firm, other):
        files = [("files", (f"{firm}-{i:03d}.pdf", pdf, "application/pdf"))
                 for i in range(N)]
        barrier.wait()
        try:
            r = client.post("/api/extract/upload", headers=hdrs[firm], files=files,
                            data={"client_id": other})   # names the OTHER firm
            answers[firm] = r
        except Exception as e:                          # pragma: no cover
            errors.append(e)

    ups = [threading.Thread(target=upload, args=(f, FIRMS[1 - i]))
           for i, f in enumerate(FIRMS)]
    for t in ups:
        t.start()
    for t in ups:
        t.join(120)
    assert not errors
    assert {f: r.status_code for f, r in answers.items()} == {f: 202 for f in FIRMS}
    for t in worker:
        t.join(300)
        assert not t.is_alive(), "a job thread did not finish"

    db.expire_all()
    for firm in FIRMS:
        job = db.get(ExtractionJob, answers[firm].json()["job_id"])
        assert job.client_id == firm
        assert (job.status, job.successful, job.failed) == ("completed", N, 0)
        docs = db.query(DocumentResult).filter(DocumentResult.job_id == job.id).all()
        assert len(docs) == N
        names = set()
        for d in docs:
            f = json.loads(d.extraction_json)["extracted_fields"]
            assert f["B2"] == d.original_filename, "a result in the wrong row"
            assert f["B2"].startswith(firm + "-"), "another firm's file"
            assert f"/clients/{firm}/jobs/{job.id}/source/" in f["B3"]
            names.add(f["B2"])
        assert names == {f"{firm}-{i:03d}.pdf" for i in range(N)}


def test_the_job_runner_itself_keeps_parallel_jobs_apart(db, _db_url, worker, tmp_path):
    """The same property one layer down: two `_run_extraction_sync` threads
    started together over their own jobs' keys."""
    from app.api.routes import extract as X
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    pdf = (bs.PDF_DIR / "INV-2024-0031.pdf").read_bytes()
    jobs = {}
    for firm in FIRMS:
        j = ExtractionJob(client_id=firm, status="pending", total_docs=N,
                          input_source="upload")
        db.add(j); db.commit(); db.refresh(j)
        keys = [get_storage().save_upload(pdf, f"{firm}-{i:03d}.pdf", j.id,
                                          client_id=firm)[0] for i in range(N)]
        jobs[firm] = (j.id, keys)
    schema = tmp_path / "s.yaml"
    schema.write_text("client_id: x\n", encoding="utf-8")
    go = threading.Barrier(len(FIRMS))

    def run(jid, keys):
        go.wait()
        X._run_extraction_sync(jid, keys, str(schema), _db_url, None,
                               str(bs.REPO_DIR), str(bs.BACKEND_DIR), str(bs.ENGINE_DIR))

    ts = [threading.Thread(target=run, args=v) for v in jobs.values()]
    for t in ts:
        t.start()
    for t in ts:
        t.join(300)
    db.expire_all()
    for firm, (jid, _) in jobs.items():
        docs = db.query(DocumentResult).filter(DocumentResult.job_id == jid).all()
        assert len(docs) == N
        assert all(json.loads(d.extraction_json)["extracted_fields"]["B2"]
                   .startswith(firm + "-") for d in docs)
        assert db.get(ExtractionJob, jid).successful == N
