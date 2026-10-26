"""
The per-firm monthly page limit (B2): TENANT_MONTHLY_PAGE_LIMIT, the firm's own
`monthly_page_limit` in its schema, and the usage route.

Under, at and over the limit; two firms independent; a new month starts from
zero; 0 means unlimited. A refused upload stores nothing and starts nothing.
"""
from __future__ import annotations

import io
from datetime import datetime
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

QA, QB = "pqAfirm", "pqBfirm"
PDF = bs.PDF_DIR / "INV-2024-0031.pdf"


@pytest.fixture(scope="module")
def firms(db, _scratch_storage):
    from app.config import settings
    from app.core.auth import create_access_token
    from app.models.models import ClientSchema
    from tests.http.conftest import _mkuser
    yaml_text = (bs.BACKEND_DIR / "engine" / "demo_accounting.yaml").read_text(encoding="utf-8")
    out = {}
    for f in (QA, QB):
        (settings.LOCAL_SCHEMAS_DIR / "clients" / f"{f}.yaml").write_text(yaml_text, encoding="utf-8")
        if not db.query(ClientSchema).filter(ClientSchema.client_id == f).first():
            db.add(ClientSchema(client_id=f, client_name=f, yaml_content=yaml_text,
                                document_types="[]"))
            db.commit()
        hdr = {}
        for role, stored in (("admin", "admin"), ("user", "client"), ("reviewer", "reviewer")):
            u = _mkuser(db, f"{f}_{role}", stored, f)
            tok = create_access_token({"sub": str(u.id), "role": u.role, "client_id": f})
            hdr[role] = {"Authorization": f"Bearer {tok}"}
        out[f] = hdr
    return out


@pytest.fixture(autouse=True)
def _inert(monkeypatch, db):
    class _T:
        def __init__(self, *a, **k): pass
        def start(self): pass
    monkeypatch.setattr("app.api.routes.extract.threading", SimpleNamespace(Thread=_T))
    from app.models.models import ExtractionJob
    for j in db.query(ExtractionJob).filter(ExtractionJob.client_id.in_([QA, QB])).all():
        db.delete(j)
    db.commit()


def _pages():
    from pypdf import PdfReader
    return len(PdfReader(str(PDF)).pages)


def _up(client, hdr, n=1):
    files = [("files", (f"q{i}.pdf", io.BytesIO(PDF.read_bytes()), "application/pdf"))
             for i in range(n)]
    return client.post("/api/extract/upload", headers=hdr, files=files)


def _limit(monkeypatch, n):
    from app.config import settings
    monkeypatch.setattr(settings, "TENANT_MONTHLY_PAGE_LIMIT", n)


def test_a_started_job_records_its_pages(client, firms, db, monkeypatch):
    from app.models.models import ExtractionJob
    _limit(monkeypatch, 0)
    r = _up(client, firms[QA]["user"], 2)
    assert r.status_code == 202
    assert db.get(ExtractionJob, r.json()["job_id"]).marks()["pages"] == 2 * _pages()


def test_limit_zero_is_unlimited(client, firms, monkeypatch):
    _limit(monkeypatch, 0)
    for _ in range(3):
        assert _up(client, firms[QA]["user"], 3).status_code == 202


def test_under_at_and_over_the_limit(client, firms, db, monkeypatch):
    from app.models.models import ExtractionJob
    p = _pages()
    _limit(monkeypatch, 3 * p)
    assert _up(client, firms[QA]["user"], 2).status_code == 202     # under
    assert _up(client, firms[QA]["user"], 1).status_code == 202     # exactly at
    before = db.query(ExtractionJob).count()
    r = _up(client, firms[QA]["user"], 1)                           # over
    assert r.status_code == 429
    assert "Monthly page limit reached" in r.json()["detail"]
    assert "Nothing was processed" in r.json()["detail"]
    assert db.query(ExtractionJob).count() == before                 # no job row


def test_one_upload_bigger_than_the_whole_limit_is_refused(client, firms, monkeypatch):
    _limit(monkeypatch, 1)
    assert _up(client, firms[QA]["user"], 2).status_code == 429


def test_two_firms_are_independent(client, firms, monkeypatch):
    p = _pages()
    _limit(monkeypatch, p)
    assert _up(client, firms[QA]["user"]).status_code == 202
    assert _up(client, firms[QA]["user"]).status_code == 429
    assert _up(client, firms[QB]["user"]).status_code == 202


def test_last_month_does_not_count(client, firms, db, monkeypatch):
    from app.models.models import ExtractionJob
    p = _pages()
    _limit(monkeypatch, p)
    r = _up(client, firms[QA]["user"])
    j = db.get(ExtractionJob, r.json()["job_id"])
    now = datetime.utcnow()
    j.created_at = datetime(now.year - (now.month == 1), (now.month - 2) % 12 + 1, 28)
    db.commit()
    assert _up(client, firms[QA]["user"]).status_code == 202


def test_month_rollover_arithmetic():
    from app.core.usage import month_start, next_month_start
    assert next_month_start(datetime(2026, 12, 31, 23, 59)) == datetime(2027, 1, 1)
    assert month_start(datetime(2027, 1, 1, 0, 0)) == datetime(2027, 1, 1)
    assert next_month_start(datetime(2026, 1, 31)) == datetime(2026, 2, 1)


def test_usage_rolls_over_at_the_month_boundary(db, firms):
    from app.core.usage import pages_used
    from app.models.models import ExtractionJob
    j = ExtractionJob(client_id=QB, status="completed", total_docs=1,
                      input_source="upload", created_at=datetime(2026, 12, 31, 23, 59))
    j.set_mark("pages", 7)
    db.add(j); db.commit()
    assert pages_used(db, QB, now=datetime(2026, 12, 31, 23, 59, 59)) >= 7
    assert pages_used(db, QB, now=datetime(2027, 1, 1, 0, 0, 1)) == 0


def test_a_deleted_or_failed_job_still_counts(db, firms):
    from app.core.usage import pages_used
    from app.models.models import ExtractionJob
    j = ExtractionJob(client_id=QB, status="failed", total_docs=1, input_source="upload")
    j.set_mark("pages", 5)
    j.set_mark("deleted", {"at": "x"})
    db.add(j); db.commit()
    assert pages_used(db, QB) >= 5


def test_a_job_from_before_the_mark_counts_one_page_per_document(db, firms):
    from app.core.usage import job_pages
    from app.models.models import ExtractionJob
    assert job_pages(ExtractionJob(client_id=QB, total_docs=4, notes="")) == 4


def test_the_firms_own_schema_overrides_the_global_limit(client, firms, db, monkeypatch):
    from app.models.models import ClientSchema
    _limit(monkeypatch, 0)
    row = db.query(ClientSchema).filter(ClientSchema.client_id == QB).first()
    saved = row.yaml_content
    row.yaml_content = saved + "\nmonthly_page_limit: 1\n"
    db.commit()
    try:
        assert _up(client, firms[QB]["user"], 2).status_code == 429
        assert _up(client, firms[QA]["user"], 2).status_code == 202   # A unaffected
        u = client.get("/api/usage", headers=firms[QB]["admin"]).json()
        assert (u["page_limit"], u["limit_source"]) == (1, "firm")
    finally:
        row.yaml_content = saved
        db.commit()


def test_the_usage_route(client, firms, auth, monkeypatch):
    p = _pages()
    _limit(monkeypatch, 10 * p)
    _up(client, firms[QA]["user"], 2)
    u = client.get("/api/usage", headers=firms[QA]["admin"]).json()
    assert u["client_id"] == QA and u["pages_used"] == 2 * p
    assert u["page_limit"] == 10 * p and u["pages_remaining"] == 8 * p
    # a firm admin sees only its own firm, whatever it asks for
    o = client.get("/api/usage", headers=firms[QB]["admin"], params={"client_id": QA}).json()
    assert o["client_id"] == QB
    for role in ("user", "reviewer"):
        assert client.get("/api/usage", headers=firms[QA][role]).status_code == 403
    # the platform admin names a firm
    s = client.get("/api/usage", headers=auth["super"], params={"client_id": QA}).json()
    assert s["pages_used"] == 2 * p
    assert client.get("/api/usage", headers=auth["super"]).status_code == 400


def test_a_drive_job_counts_one_page_per_file_and_is_refused_over(client, firms, db,
                                                                   monkeypatch):
    from app.config import settings
    from app.models.models import ExtractionJob

    class _Drive:
        is_configured = is_authenticated = True

        def list_files(self, folder_id):
            return [SimpleNamespace(id=f"f{i}", name=f"f{i}.pdf", is_supported=True)
                    for i in range(3)]
    monkeypatch.setattr("app.api.routes.drive._get_drive", lambda: _Drive())
    monkeypatch.setattr("app.api.routes.drive._run_drive_extraction", lambda *a, **k: None)
    monkeypatch.setattr(settings, "DRIVE_TENANT", QA)
    _limit(monkeypatch, 4)
    r = client.post("/api/drive/extract", headers=firms[QA]["user"],
                    params={"folder_id": "x", "client_id": QA})
    assert r.status_code == 202, r.text
    assert db.get(ExtractionJob, r.json()["job_id"]).marks()["pages"] == 3
    r = client.post("/api/drive/extract", headers=firms[QA]["user"],
                    params={"folder_id": "x", "client_id": QA})
    assert r.status_code == 429
