"""
Side channels between firms (A2): storage keys, caches, headers, logs.

The route guard (test_tenant_isolation_all_routes.py) proves no route hands
firm B firm A's records. These are the ways around a route: a storage key two
firms could share or guess, an in-process cache keyed by something other than
the firm, a response a shared cache could keep and replay to the next caller,
and a log line naming another firm. The audit itself is docs/SECURITY.md,
"Isolation between firms".
"""
from __future__ import annotations

import io
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

A, B = "scAfirm", "scBfirm"
SAME_NAME = "invoice.pdf"


# ── storage keys ─────────────────────────────────────────────────────────────

class TestStorageKeys:
    def test_every_key_leads_with_its_firm(self):
        from app.core.storage import StorageService as S
        for k in (S.upload_key(A, 7, SAME_NAME), S.job_prefix(A, 7)):
            assert k.startswith(f"clients/{A}/jobs/7")
        assert S.upload_key(A, 7, SAME_NAME) != S.upload_key(B, 7, SAME_NAME)

    @pytest.mark.parametrize("name", [
        f"../../{A}/jobs/7/source/x.pdf", f"..\\..\\{A}\\x.pdf",
        f"/clients/{A}/jobs/7/source/x.pdf", "C:/x.pdf", "x/../../y.pdf"])
    def test_a_hostile_file_name_cannot_leave_its_firm(self, name):
        from app.core.storage import StorageService as S
        k = S.upload_key(B, 7, name)
        assert k.startswith(f"clients/{B}/jobs/7/source/")
        assert ".." not in k.split("/") and k.count("/") == 5

    @pytest.mark.parametrize("cid", ["../" + A, f"{B}/../{A}", A + " ", A + ".",
                                     A.replace("A", "A b"), "a b", "a_b/"])
    def test_a_firm_id_that_would_be_normalised_is_refused(self, cid):
        """`a b` and `a_b`, `../x` and `x`: normalising a firm id lets two firms
        share a prefix and a schema file, so such an id is refused outright."""
        from app.core.storage import StorageError, StorageService as S
        for build in (lambda: S.upload_key(cid, 7, SAME_NAME),
                      lambda: S.job_prefix(cid, 7), lambda: S.schema_key(cid)):
            with pytest.raises(StorageError):
                build()

    def test_no_firm_id_keeps_its_fallback(self):
        from app.core.storage import StorageService as S
        assert S.upload_key(None, 7, SAME_NAME).startswith("clients/anon/")

    @pytest.mark.parametrize("cid", ["a b", "../x", "x/", "x.", "-x", ""])
    def test_the_api_cannot_create_such_a_firm(self, client, auth, cid):
        r = client.post("/api/admin/users", headers=auth["super"],
                        json={"username": "bad_cid_user", "display_name": "x",
                              "password": "long-enough-1", "client_id": cid})
        assert r.status_code == 422, r.text
        y = "client_id: '" + cid + "'\nclient_name: x\n"
        r = client.post("/api/schemas", headers=auth["super"],
                        files={"file": ("s.yaml", y.encode(), "application/x-yaml")})
        assert r.status_code == 400, r.text


# ── two firms, the same file name: caches keyed by firm ─────────────────────

@pytest.fixture(scope="module")
def two_firms(db, _scratch_storage):
    from app.core.auth import create_access_token
    from app.core.storage import get_storage
    from app.models.models import DocumentResult, ExtractionJob
    from app.config import settings
    from tests.http.conftest import _mkuser
    yaml_text = (bs.BACKEND_DIR / "engine" / "demo_accounting.yaml").read_text(encoding="utf-8")
    for firm in (A, B):
        (settings.LOCAL_SCHEMAS_DIR / "clients" / f"{firm}.yaml").write_text(
            yaml_text, encoding="utf-8")
    out = {}
    for firm, pdf in ((A, "INV-2024-0031.pdf"), (B, "CHQ-001847.pdf")):
        u = _mkuser(db, f"{firm}_user", "client", firm)
        job = ExtractionJob(user_id=u.id, client_id=firm, status="completed",
                            total_docs=1, input_source="upload")
        db.add(job); db.commit(); db.refresh(job)
        key, _ = get_storage().save_upload((bs.PDF_DIR / pdf).read_bytes(), SAME_NAME,
                                           job.id, client_id=firm)
        doc = DocumentResult(job_id=job.id, filename=SAME_NAME, original_filename=SAME_NAME,
                             extraction_json=json.dumps({"extracted_fields": {}}), s3_key=key)
        db.add(doc); db.commit(); db.refresh(doc)
        tok = create_access_token({"sub": str(u.id), "role": u.role, "client_id": firm})
        out[firm] = (job.id, doc.id, {"Authorization": f"Bearer {tok}"})
    return out


def _image(client, firm_entry):
    j, d, h = firm_entry
    r = client.get(f"/api/jobs/{j}/docs/{d}/pages/1/image", headers=h)
    assert r.status_code == 200, r.text
    return r.content


def test_the_page_cache_never_serves_one_firm_the_other_firms_reading(client, two_firms):
    """Both firms store a file called invoice.pdf (different documents); the
    review screen caches readings and images in memory. Each firm gets its own
    page, whichever firm's was read first."""
    from app.api.routes import review
    with review._cache_lock:
        review._cache.clear()
    a1, b1 = _image(client, two_firms[A]), _image(client, two_firms[B])
    with review._cache_lock:
        assert len({k for k in review._cache if SAME_NAME in k}) == 2
        review._cache.clear()
    b2, a2 = _image(client, two_firms[B]), _image(client, two_firms[A])
    assert a1 != b1 and a1 == a2 and b1 == b2


# ── response headers ─────────────────────────────────────────────────────────

def test_api_responses_are_never_shared_cacheable(client, two_firms):
    j, d, h = two_firms[A]
    for path in (f"/api/jobs/{j}", f"/api/jobs/{j}/results", "/api/jobs",
                 f"/api/jobs/{j}/export", "/api/templates", "/api/auth/me"):
        r = client.get(path, headers=h)
        assert r.status_code == 200, (path, r.text[:120])
        assert r.headers.get("cache-control") == "no-store", path
        assert "authorization" in r.headers.get("vary", "").lower(), path
    r = client.get(f"/api/jobs/{j}", headers={"Authorization": "Bearer nope"})
    assert r.headers.get("cache-control") == "no-store"     # errors too


def test_the_page_image_is_private_to_the_viewers_browser(client, two_firms):
    j, d, h = two_firms[A]
    r = client.get(f"/api/jobs/{j}/docs/{d}/pages/1/image", headers=h)
    assert r.status_code == 200
    cc = r.headers["cache-control"]
    assert cc.startswith("private") and "public" not in cc and "s-maxage" not in cc


def test_export_file_names_carry_no_firm(client, two_firms):
    j, d, h = two_firms[A]
    for path in (f"/api/jobs/{j}/export", f"/api/jobs/{j}/export/zip"):
        cd = client.get(path, headers=h).headers.get("content-disposition", "")
        assert cd and A not in cd and B not in cd


# ── logs ─────────────────────────────────────────────────────────────────────

def test_naming_another_firm_is_logged_by_user_id_only(client, two_firms, capsys,
                                                       monkeypatch):
    from types import SimpleNamespace

    class _T:
        def __init__(self, *a, **k): pass
        def start(self): pass
    monkeypatch.setattr("app.api.routes.extract.threading", SimpleNamespace(Thread=_T))
    j, d, h = two_firms[B]
    pdf = (bs.PDF_DIR / "INV-2024-0031.pdf").read_bytes()
    r = client.post("/api/extract/upload", headers=h, data={"client_id": A},
                    files=[("files", ("x.pdf", io.BytesIO(pdf), "application/pdf"))])
    assert r.status_code == 202
    out = capsys.readouterr()
    text = out.out + out.err
    assert "[TENANCY]" in text
    assert A not in text and B not in text
