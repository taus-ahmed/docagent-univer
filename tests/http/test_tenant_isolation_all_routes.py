"""
Two firms, every route: firm B's users never receive firm A's data.

Routes are enumerated from the running app (`app.routes`), and every one must
appear in ROUTES (with a case saying how it is attacked) or in ALLOWLIST (with
a reason). A route added tomorrow that is in neither fails
`test_every_route_is_covered_or_allowlisted` — that is the guard.

Each firm has an admin, a reviewer and a user, and firm A owns one record of
every kind: a job with a result (and its stored source file, so page images are
real), review marks, a shared template, a schema, a watch folder, and the Drive
the server's credential belongs to. For every route that takes an id, each of
firm B's three users calls it with firm A's ids and must get EXACTLY the answer
a missing id gets (status and body, the id itself normalised) — so firm A's ids
cannot even be probed. Lists, exports and downloads are scanned for firm A's
markers; mutations are followed by a check that firm A's record is unchanged.
Positive controls prove firm A's own admin does reach every id used, so a 404
here is the scope rule, not a broken fixture.
"""
from __future__ import annotations

import io
import json
import zipfile
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from app.api.routes import drive as _drive_mod  # noqa: E402

_REAL_WATCH_CHECK = _drive_mod._do_watch_check    # before _inert stubs it

A, B = "isoAfirm", "isoBfirm"
MISSING = "999999"
A_MARKERS = ("isoAfirm", "isoA-template-marker", "isoA-secret-invoice",
             "ISOA-SECRET-VALUE", "isoA-watch-folder", "isoA Firm Name",
             "isoA-drive-file", "isoA_admin", "isoA_reviewer", "isoA_user")

#: Routes that hold no firm's data, each with the reason. Adding to this is a
#: security decision and should look like one in the diff.
ALLOWLIST = {
    ("POST", "/api/auth/login"): "issues the token; public",
    ("POST", "/api/auth/logout"): "stateless no-op; public",
    ("GET", "/health"): "public health check, no data",
    ("GET", "/"): "public banner, no data",
    ("GET", "/api/review/reasons"): "static reason-code vocabulary",
    ("POST", "/api/templates/shape"): "pure function of the posted grid; reads nothing stored",
    ("POST", "/api/extract/page-count"): "pure function of the posted files; reads and stores nothing",
    ("GET", "/api/drive/auth/status"): "two booleans about the server's credential",
    ("POST", "/api/drive/auth"): "starts the server credential's OAuth; returns no data",
}

#: (method, path) -> case. "id": path params filled with firm A's ids;
#: "list": scanned for markers; "body": a request whose BODY names firm A;
#: "self": the caller's own record only; "demo": demo tenants only.
ROUTES = {
    ("GET", "/api/auth/me"): "self",
    ("PUT", "/api/auth/me"): "self",
    ("POST", "/api/auth/change-password"): "self",
    ("POST", "/api/admin/tenants"): "body",
    ("GET", "/api/admin/tenants"): "list",
    ("POST", "/api/admin/tenants/{client_id}/deactivate"): "id",
    ("POST", "/api/admin/tenants/{client_id}/activate"): "id",
    ("POST", "/api/extract/upload"): "body",
    ("GET", "/api/jobs"): "list",
    ("GET", "/api/jobs/{job_id}"): "id",
    ("GET", "/api/jobs/{job_id}/export"): "id",
    ("GET", "/api/jobs/{job_id}/export/zip"): "id",
    ("GET", "/api/jobs/{job_id}/results"): "id",
    ("GET", "/api/jobs/{job_id}/inferred-templates"): "id",
    ("PUT", "/api/jobs/{job_id}/docs/{doc_id}"): "id",
    ("PATCH", "/api/jobs/{job_id}/docs/{doc_id}/fields/{ref}"): "id",
    ("POST", "/api/jobs/{job_id}/docs/{doc_id}/approve"): "id",
    ("DELETE", "/api/jobs/{job_id}"): "id",
    ("DELETE", "/api/jobs/{job_id}/data"): "id",
    ("POST", "/api/export/combined"): "body",
    ("POST", "/api/export/perfile"): "body",
    ("GET", "/api/templates"): "list",
    ("GET", "/api/templates/{template_id}"): "id",
    ("POST", "/api/templates"): "list",
    ("PUT", "/api/templates/{template_id}"): "id",
    ("DELETE", "/api/templates/{template_id}"): "id",
    ("GET", "/api/schemas"): "list",
    ("POST", "/api/schemas"): "body",
    ("GET", "/api/schemas/{client_id}"): "id",
    ("DELETE", "/api/schemas/{client_id}"): "id",
    ("GET", "/api/drive/folders/{folder_id}"): "id",
    ("POST", "/api/drive/extract"): "body",
    ("GET", "/api/watch"): "list",
    ("POST", "/api/watch"): "body",
    ("DELETE", "/api/watch/{watch_id}"): "id",
    ("POST", "/api/watch/check"): "body",
    ("GET", "/api/admin/users"): "list",
    ("POST", "/api/admin/users"): "body",
    ("PUT", "/api/admin/users/{user_id}"): "id",
    ("DELETE", "/api/admin/users/{user_id}"): "id",
    ("GET", "/api/admin/stats"): "list",
    ("GET", "/api/usage"): "list",
    ("GET", "/api/demo/sample-docs"): "demo",
    ("GET", "/api/demo/sample-docs/{filename}/download"): "demo",
    ("POST", "/api/demo/sample-docs/{filename}/extract"): "demo",
    ("GET", "/api/jobs/{job_id}/review"): "id",
    ("GET", "/api/jobs/{job_id}/charts"): "id",
    ("POST", "/api/jobs/{job_id}/docs/{doc_id}/review"): "id",
    ("GET", "/api/jobs/{job_id}/docs/{doc_id}/pages/{page}"): "id",
    ("GET", "/api/jobs/{job_id}/docs/{doc_id}/pages/{page}/image"): "id",
}

#: JSON bodies for id routes that need one (valid, so validation never
#: answers before the scope check does).
BODIES = {
    ("PUT", "/api/jobs/{job_id}/docs/{doc_id}"): {"extracted_data": {"B2": {"value": "x"}}},
    ("PATCH", "/api/jobs/{job_id}/docs/{doc_id}/fields/{ref}"): {"value": "x"},
    ("PUT", "/api/templates/{template_id}"): {"name": "hijacked"},
    ("PUT", "/api/admin/users/{user_id}"): {"display_name": "hijacked"},
    ("POST", "/api/jobs/{job_id}/docs/{doc_id}/review"): {"scope": "document"},
}


def _app_routes(app):
    from fastapi.routing import APIRoute
    out = set()
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                out.add((m, r.path))
    return out


def test_every_route_is_covered_or_allowlisted(app):
    routes = _app_routes(app)
    uncovered = sorted(routes - set(ROUTES) - set(ALLOWLIST))
    assert not uncovered, (
        "routes with no tenant-isolation case — add each to ROUTES in this file "
        "(and to the checks below) or to ALLOWLIST with a reason:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in uncovered))
    stale = sorted((set(ROUTES) | set(ALLOWLIST)) - routes)
    assert not stale, f"cases for routes that no longer exist: {stale}"
    assert not set(ROUTES) & set(ALLOWLIST)


# ── the two firms ────────────────────────────────────────────────────────────

def _mkuser(db, username, role, client_id):
    from tests.http.conftest import _mkuser as mk
    return mk(db, username, role, client_id)


def _hdr(u):
    from app.core.auth import create_access_token
    tok = create_access_token({"sub": str(u.id), "role": u.role, "client_id": u.client_id})
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def firms(db, _scratch_storage):
    from app.config import settings
    from app.core.storage import get_storage
    from app.models.models import (ClientSchema, ColumnTemplate, DocumentResult,
                                   ExtractionJob, WatchFolder)
    yaml_text = (bs.BACKEND_DIR / "engine" / "demo_accounting.yaml").read_text(encoding="utf-8")
    out = {}
    for firm, tag in ((A, "isoA"), (B, "isoB")):
        (settings.LOCAL_SCHEMAS_DIR / "clients").mkdir(parents=True, exist_ok=True)
        (settings.LOCAL_SCHEMAS_DIR / "clients" / f"{firm}.yaml").write_text(
            yaml_text, encoding="utf-8")
        if not db.query(ClientSchema).filter(ClientSchema.client_id == firm).first():
            db.add(ClientSchema(client_id=firm, client_name=f"{tag} Firm Name",
                                yaml_content=yaml_text, document_types="[]"))
            db.commit()
        us = {r: _mkuser(db, f"{tag}_{r}", role, firm)
              for r, role in (("admin", "admin"), ("reviewer", "reviewer"),
                              ("user", "client"))}
        job = ExtractionJob(user_id=us["user"].id, client_id=firm, status="completed",
                            total_docs=1, successful=1, input_source="upload")
        db.add(job); db.commit(); db.refresh(job)
        pdf = bs.PDF_DIR / "INV-2024-0031.pdf"
        fname = f"{tag}-secret-invoice.pdf"
        key, _ = get_storage().save_upload(pdf.read_bytes(), fname, job.id, client_id=firm)
        value = f"{tag.upper()}-SECRET-VALUE"
        ed = {"extracted_fields": {"B2": value},
              "extracted_data": {"Invoice Number": {"value": value, "confidence": "high",
                                                    "ref": "B2"}},
              "slot_map": {"fields": [{"ref": "B2", "row_label": "Invoice Number"}],
                           "tables": []},
              "field_provenance": {"B2": {"source": value, "page": 1, "grounded": True,
                                          "review_required": False, "review_reasons": []}},
              "validation": {"confidence_map": {"B2": "high"}, "flagged_fields": []},
              "template_type": "slot", "document_type": "invoice"}
        doc = DocumentResult(job_id=job.id, filename=fname, original_filename=fname,
                             document_type="invoice", extraction_json=json.dumps(ed),
                             overall_confidence="high", s3_key=key)
        db.add(doc); db.commit(); db.refresh(doc)
        tpl = ColumnTemplate(name=f"{tag}-template-marker", document_type="invoice",
                             description=json.dumps({"cells": {"0,0": {"value": "Invoice Number"}}}),
                             columns_json="[]", user_id=us["admin"].id, client_id=firm,
                             is_shared=True)
        db.add(tpl); db.commit(); db.refresh(tpl)
        wf = WatchFolder(user_id=us["admin"].id, folder_id=f"{tag}DriveFolder",
                         folder_name=f"{tag}-watch-folder", client_id=firm)
        db.add(wf); db.commit(); db.refresh(wf)
        out[firm] = SimpleNamespace(users=us, hdr={r: _hdr(u) for r, u in us.items()},
                                    job=job.id, doc=doc.id, tpl=tpl.id, watch=wf.id,
                                    folder=f"{tag}DriveFolder", key=key)
    return out


class _FakeDrive:
    """The server-wide Drive credential, which belongs to firm A."""
    is_configured = is_authenticated = True

    def list_folders(self, folder_id):
        return [SimpleNamespace(id="isoAsub", name="isoA-drive-sub")]

    def list_files(self, folder_id):
        return [SimpleNamespace(id="isoAfile", name="isoA-drive-file.pdf",
                                mime_type="application/pdf", size=1,
                                modified_time="", is_supported=True)]

    def download_file(self, *a, **k):
        return None


@pytest.fixture(autouse=True)
def _inert(monkeypatch):
    """No extraction thread, no Drive background task, a fake Drive that is
    firm A's (DRIVE_TENANT), demo off."""
    from app.config import settings

    class _Thread:
        def __init__(self, *a, **k): pass
        def start(self): pass
    # the route module's own `threading`, not the global module: patching
    # threading.Thread itself breaks subprocess reads (pdf2image) on Windows
    monkeypatch.setattr("app.api.routes.extract.threading", SimpleNamespace(Thread=_Thread))
    monkeypatch.setattr("app.api.routes.drive._get_drive", lambda: _FakeDrive())
    monkeypatch.setattr("app.api.routes.drive._run_drive_extraction", lambda *a, **k: None)
    monkeypatch.setattr("app.api.routes.drive._do_watch_check", lambda *a, **k: None)
    monkeypatch.setattr(settings, "DRIVE_TENANT", A)
    monkeypatch.setattr(settings, "DEMO_CLIENT_IDS", "")


def _fill(path, ids):
    for k, v in ids.items():
        path = path.replace("{" + k + "}", str(v))
    return path


def _a_ids(firms):
    a = firms[A]
    return {"job_id": a.job, "doc_id": a.doc, "ref": "B2", "template_id": a.tpl,
            "client_id": A, "folder_id": a.folder, "watch_id": a.watch,
            "user_id": a.users["user"].id, "page": 1}


MISSING_IDS = {"job_id": MISSING, "doc_id": MISSING, "ref": "B2",
               "template_id": MISSING, "client_id": "noSuchFirm",
               "folder_id": "noSuchFolder", "watch_id": MISSING,
               "user_id": MISSING, "page": 1}


def _norm(text, ids):
    for k, v in ids.items():
        if k not in ("ref", "page"):
            text = text.replace(str(v), "<ID>")
    return text


def _scan_bytes(content: bytes) -> list[str]:
    """Every marker in a response body, opening xlsx/zip (and zips in zips)."""
    chunks = [content]
    if content[:2] == b"PK":
        def walk(b):
            with zipfile.ZipFile(io.BytesIO(b)) as z:
                for n in z.namelist():
                    data = z.read(n)
                    chunks.append(n.encode())
                    chunks.append(data)
                    if data[:2] == b"PK":
                        walk(data)
        walk(content)
    blob = b"\n".join(chunks).decode("utf-8", "replace")
    return [m for m in A_MARKERS if m in blob]


ID_ROUTES = sorted(k for k, v in ROUTES.items() if v == "id")


B_ROLES = ("admin", "reviewer", "user")


@pytest.mark.parametrize("route", ID_ROUTES, ids=lambda r: f"{r[0]} {r[1]}")
@pytest.mark.parametrize("role", B_ROLES)
def test_firm_a_ids_answer_firm_b_exactly_like_missing_ids(client, firms, route, role):
    method, path = route
    hdr = firms[B].hdr[role]
    body = BODIES.get(route)
    ids = _a_ids(firms)
    got = client.request(method, _fill(path, ids), headers=hdr, json=body)
    miss = client.request(method, _fill(path, MISSING_IDS), headers=hdr, json=body)
    assert got.status_code >= 400, (got.status_code, got.text[:200])
    assert got.status_code == miss.status_code, (
        f"{role}: firm A's id answered {got.status_code}, a missing id {miss.status_code}")
    assert _norm(got.text, ids) == _norm(miss.text, MISSING_IDS)
    # the caller's own path echoed back is not firm A's data
    assert not _scan_bytes(_norm(got.text, ids).encode())


# GET routes on which firm A's own admin must SUCCEED with the same ids — the
# proof that the 404s above are the scope rule and not a dead fixture.
POSITIVE = [r for r in ID_ROUTES if r[0] == "GET"]


@pytest.mark.parametrize("route", POSITIVE, ids=lambda r: f"{r[0]} {r[1]}")
def test_firm_a_reaches_its_own_records(client, firms, route):
    method, path = route
    r = client.request(method, _fill(path, _a_ids(firms)), headers=firms[A].hdr["admin"])
    assert r.status_code == 200, (route, r.status_code, r.text[:200])


def test_firm_a_records_survive_every_attack(client, firms, db):
    """Run after the parametrised attacks (file order): nothing of firm A's
    was changed, cancelled, deleted or deactivated by firm B."""
    from app.models.models import (ClientSchema, ColumnTemplate, DocumentResult,
                                   ExtractionJob, User, WatchFolder)
    db.expire_all()
    a = firms[A]
    job = db.get(ExtractionJob, a.job)
    assert job.status == "completed" and not job.marks().get("deleted")
    doc = db.get(DocumentResult, a.doc)
    assert doc is not None and not doc.reviewed
    assert "ISOA-SECRET-VALUE" in doc.extraction_json
    assert db.get(ColumnTemplate, a.tpl).name == "isoA-template-marker"
    assert db.query(ClientSchema).filter(ClientSchema.client_id == A).first()
    assert db.get(WatchFolder, a.watch).is_active
    u = db.get(User, a.users["user"].id)
    assert u.is_active and u.display_name == "isoA_user"


LIST_ROUTES = [("GET", "/api/jobs"), ("GET", "/api/templates"), ("GET", "/api/schemas"),
               ("GET", "/api/watch"), ("GET", "/api/admin/users"),
               ("GET", "/api/auth/me"), ("GET", "/api/admin/tenants")]


@pytest.mark.parametrize("route", LIST_ROUTES, ids=lambda r: r[1])
@pytest.mark.parametrize("role", B_ROLES)
def test_lists_carry_nothing_of_firm_a(client, firms, route, role):
    r = client.request(*route, headers=firms[B].hdr[role])
    assert r.status_code in (200, 403), r.text[:200]
    assert not _scan_bytes(r.content), r.text[:300]
    if route == ("GET", "/api/jobs") and r.status_code == 200:
        assert firms[A].job not in {j["id"] for j in r.json()}


def test_lists_do_show_firm_a_its_own(client, firms):
    for route in LIST_ROUTES[:5]:
        r = client.request(*route, headers=firms[A].hdr["admin"])
        assert r.status_code == 200 and _scan_bytes(r.content), route


@pytest.mark.parametrize("role", B_ROLES)
def test_usage_is_only_the_callers_firm(client, firms, role):
    r = client.get("/api/usage", headers=firms[B].hdr[role], params={"client_id": A})
    if role == "admin":
        assert r.status_code == 200 and r.json()["client_id"] == B
    else:
        assert r.status_code == 403
    assert not _scan_bytes(r.content)


def test_stats_count_only_the_callers_firm(client, firms):
    r = client.get("/api/admin/stats", headers=firms[B].hdr["admin"])
    assert r.status_code == 200
    s = r.json()
    assert s["total_users"] == 3
    from app.models.models import ExtractionJob
    assert s["total_jobs"] == client.app.state._sessionmaker().query(ExtractionJob) \
        .filter(ExtractionJob.client_id == B).count()


@pytest.mark.parametrize("role", B_ROLES)
def test_self_routes_touch_only_the_caller(client, firms, role):
    r = client.put("/api/auth/me", headers=firms[B].hdr[role],
                   json={"display_name": f"isoB_{role}"})
    assert r.status_code == 200 and r.json()["client_id"] == B
    assert not _scan_bytes(r.content)
    # the profile route ignores tenant and role, whatever the body says
    r = client.put("/api/auth/me", headers=firms[B].hdr[role],
                   json={"client_id": A, "role": "admin"})
    assert r.status_code == 200 and r.json()["client_id"] == B
    assert r.json()["role"] == firms[B].users[role].role


@pytest.mark.parametrize("role", B_ROLES)
def test_change_password_touches_only_the_caller(client, firms, role, db):
    from app.models.models import User
    before = db.get(User, firms[A].users[role].id).password_hash
    r = client.post("/api/auth/change-password", headers=firms[B].hdr[role],
                    json={"current_password": "wrong", "new_password": "x" * 14})
    assert r.status_code == 400
    db.expire_all()
    assert db.get(User, firms[A].users[role].id).password_hash == before


@pytest.mark.parametrize("role", B_ROLES)
def test_only_the_platform_admin_creates_a_firm(client, firms, role):
    r = client.post("/api/admin/tenants", headers=firms[B].hdr[role],
                    json={"client_id": "isoCfirm", "client_name": "c",
                          "admin_username": f"isoC_{role}"})
    assert r.status_code == 403


def test_a_new_template_lands_in_the_callers_firm(client, firms, db):
    from app.models.models import ColumnTemplate
    r = client.post("/api/templates", headers=firms[B].hdr["admin"],
                    json={"name": "isoB-made", "document_type": "invoice",
                          "description": json.dumps({"cells": {"0,0": {"value": "X"}}}),
                          "columns": [], "is_shared": True})
    assert r.status_code == 201, r.text
    assert db.get(ColumnTemplate, r.json()["id"]).client_id == B


# ── routes whose BODY names firm A ───────────────────────────────────────────

@pytest.mark.parametrize("role", B_ROLES)
def test_upload_naming_firm_a_lands_in_firm_b(client, firms, db, role):
    from app.models.models import ExtractionJob
    pdf = (bs.PDF_DIR / "INV-2024-0031.pdf").read_bytes()
    r = client.post("/api/extract/upload", headers=firms[B].hdr[role],
                    data={"client_id": A},
                    files=[("files", ("x.pdf", io.BytesIO(pdf), "application/pdf"))])
    assert r.status_code == 202, r.text
    assert db.get(ExtractionJob, r.json()["job_id"]).client_id == B


@pytest.mark.parametrize("role", B_ROLES)
def test_upload_with_firm_a_template_is_a_missing_template(client, firms, role):
    pdf = (bs.PDF_DIR / "INV-2024-0031.pdf").read_bytes()

    def up(tid):
        return client.post("/api/extract/upload", headers=firms[B].hdr[role],
                           data={"template_id": str(tid)},
                           files=[("files", ("x.pdf", io.BytesIO(pdf), "application/pdf"))])
    got, miss = up(firms[A].tpl), up(MISSING)
    assert got.status_code == miss.status_code == 404
    assert got.text == miss.text


@pytest.mark.parametrize("kind", ["combined", "perfile"])
@pytest.mark.parametrize("role", B_ROLES)
def test_flat_exports_of_firm_a_job_are_missing(client, firms, kind, role):
    hdr = firms[B].hdr[role]
    got = client.post(f"/api/export/{kind}", headers=hdr, json={"job_id": firms[A].job})
    miss = client.post(f"/api/export/{kind}", headers=hdr, json={"job_id": int(MISSING)})
    assert got.status_code == miss.status_code == 404
    assert got.text == miss.text


@pytest.mark.parametrize("kind", ["combined", "perfile"])
def test_flat_export_with_firm_a_template_is_missing(client, firms, kind):
    hdr = firms[B].hdr["admin"]
    got = client.post(f"/api/export/{kind}", headers=hdr,
                      json={"job_id": firms[B].job, "template_id": firms[A].tpl})
    miss = client.post(f"/api/export/{kind}", headers=hdr,
                       json={"job_id": firms[B].job, "template_id": int(MISSING)})
    assert got.status_code == miss.status_code and got.text == miss.text
    assert not _scan_bytes(got.content)


@pytest.mark.parametrize("path", ["/api/jobs/{j}/export", "/api/jobs/{j}/export/zip"])
def test_exports_carry_only_their_own_firm(client, firms, path):
    own = client.get(path.format(j=firms[B].job), headers=firms[B].hdr["admin"])
    assert own.status_code == 200 and not _scan_bytes(own.content)
    theirs = client.get(path.format(j=firms[A].job), headers=firms[A].hdr["admin"])
    assert theirs.status_code == 200 and "ISOA-SECRET-VALUE" in _scan_bytes(theirs.content)


@pytest.mark.parametrize("kind", ["combined", "perfile"])
def test_flat_exports_carry_only_their_own_firm(client, firms, kind):
    own = client.post(f"/api/export/{kind}", headers=firms[B].hdr["admin"],
                      json={"job_id": firms[B].job})
    assert own.status_code == 200 and not _scan_bytes(own.content)


def test_schema_upload_naming_firm_a_is_refused(client, firms, db):
    from app.models.models import ClientSchema
    y = f"client_id: {A}\nclient_name: hijacked\ndocument_types: {{}}\n"
    got = client.post("/api/schemas", headers=firms[B].hdr["admin"],
                      files={"file": ("s.yaml", y.encode(), "application/x-yaml")})
    assert got.status_code == 404
    db.expire_all()
    assert db.query(ClientSchema).filter(ClientSchema.client_id == A).first().client_name \
        == "isoA Firm Name"


@pytest.mark.parametrize("role", B_ROLES)
def test_admin_user_creation_cannot_target_firm_a(client, firms, role):
    r = client.post("/api/admin/users", headers=firms[B].hdr[role],
                    json={"username": f"isoB_mk_{role}", "display_name": "x",
                          "password": "long-enough-1", "client_id": A})
    assert r.status_code in (403, 404), r.text


# ── Drive: one server-wide credential ────────────────────────────────────────

@pytest.mark.parametrize("role", B_ROLES)
def test_drive_is_closed_to_a_firm_it_does_not_belong_to(client, firms, db, role):
    """The server's Drive credential is firm A's (DRIVE_TENANT). Firm B must
    not browse it, extract from it, watch a folder in it, or run the watcher."""
    from app.models.models import ExtractionJob, WatchFolder
    hdr = firms[B].hdr[role]
    r = client.get("/api/drive/folders/root", headers=hdr)
    assert r.status_code == 403 and not _scan_bytes(r.content), r.text[:200]
    before = db.query(ExtractionJob).count()
    r = client.post("/api/drive/extract", headers=hdr,
                    params={"folder_id": firms[A].folder, "client_id": A})
    assert r.status_code == 403, r.text[:200]
    assert db.query(ExtractionJob).count() == before
    r = client.post("/api/watch", headers=hdr,
                    json={"folder_id": firms[A].folder, "folder_name": "x", "client_id": A})
    assert r.status_code == 403, r.text[:200]
    assert not db.query(WatchFolder).filter(WatchFolder.folder_id == firms[A].folder,
                                            WatchFolder.client_id == B).count()
    assert client.post("/api/watch/check", headers=hdr).status_code == 403


def test_drive_stays_open_to_its_own_firm(client, firms, db):
    from app.models.models import ExtractionJob, WatchFolder
    r = client.get("/api/drive/folders/root", headers=firms[A].hdr["user"])
    assert r.status_code == 200 and "isoA-drive-file" in r.text
    r = client.post("/api/drive/extract", headers=firms[A].hdr["user"],
                    params={"folder_id": "f", "client_id": B})
    assert r.status_code == 202, r.text
    assert db.get(ExtractionJob, r.json()["job_id"]).client_id == A
    r = client.post("/api/watch", headers=firms[A].hdr["admin"],
                    json={"folder_id": "isoAnew", "folder_name": "n", "client_id": B})
    assert r.status_code == 201, r.text
    assert db.get(WatchFolder, r.json()["id"]).client_id == A


def test_drive_status_says_not_configured_to_another_firm(client, firms):
    r = client.get("/api/drive/auth/status", headers=firms[B].hdr["admin"])
    assert r.status_code == 200
    assert (r.json()["is_configured"], r.json()["is_authenticated"]) == (False, False)
    r = client.get("/api/drive/auth/status", headers=firms[A].hdr["admin"])
    assert r.json()["is_configured"] is True


def test_the_watcher_never_processes_another_firms_folder(firms, db, monkeypatch):
    """A watch row naming firm B (left from before DRIVE_TENANT) is never
    handed to the watcher, even when firm B's own user triggers the check."""
    import sys
    import types
    from app.models.models import WatchFolder
    stale = WatchFolder(user_id=firms[B].users["admin"].id, folder_id="isoBold",
                        folder_name="old", client_id=B)
    db.add(stale); db.commit()
    seen = []
    fake = types.ModuleType("drive_watcher")
    fake.check_watched_folders = lambda fdb, verbose=False: seen.extend(fdb.get_watch_folders())
    monkeypatch.setitem(sys.modules, "drive_watcher", fake)
    url = str(db.bind.url)
    _REAL_WATCH_CHECK(firms[B].users["admin"].id, url)
    assert seen == []
    _REAL_WATCH_CHECK(firms[A].users["admin"].id, url)
    assert {w["client_id"] for w in seen} == {A}


def test_drive_is_closed_to_everyone_when_no_firm_owns_it(client, firms, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "DRIVE_TENANT", "")
    for f in (A, B):
        assert client.get("/api/drive/folders/root",
                          headers=firms[f].hdr["admin"]).status_code == 403


# ── demo routes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", B_ROLES)
def test_demo_routes_do_not_exist_for_a_firm(client, firms, role):
    hdr = firms[B].hdr[role]
    for m, p in (("GET", "/api/demo/sample-docs"),
                 ("GET", "/api/demo/sample-docs/x.pdf/download"),
                 ("POST", "/api/demo/sample-docs/x.pdf/extract")):
        assert client.request(m, p, headers=hdr).status_code == 404
