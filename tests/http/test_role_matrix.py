"""
Every role against every route group (docs/proposals/roles.md, `app/core/permissions.py`).

Principals, all but `other` in tenant acme_001:

    super     admin, no client_id      platform_admin (derived)
    acme      admin, client_id         tenant_admin
    cadm      company_admin            legacy role, today's powers
    rev       reviewer                 views/reviews/exports the firm's jobs
    acme2     client                   owns the job under test
    acme3     client                   same firm, NOT the owner
    other     client, other_002        another firm
    inactive  client, is_active=False
    anon      no token

A cell is the expected outcome: "ok" (anything but 401/403/404), 403 (a role
the route refuses), 404 (a job outside the caller's scope, answered like a
missing id), "auth" (401, or FastAPI's 403 for a missing bearer token).
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

PRINCIPALS = ["super", "acme", "cadm", "rev", "acme2", "acme3", "other",
              "inactive", "anon"]

#        group           super  acme  cadm   rev   acme2  acme3  other
MATRIX = {
    "job.view":     ["ok", "ok", "ok", "ok", "ok", 404, 404],
    "job.review":   ["ok", "ok", "ok", "ok", "ok", 404, 404],
    "job.export":   ["ok", "ok", "ok", "ok", "ok", 404, 404],
    "job.cancel":   ["ok", "ok", "ok", 403, "ok", 404, 404],
    "job.list":     ["ok", "ok", "ok", "ok", "ok", "ok", "ok"],
    "upload":       ["ok", "ok", "ok", "ok", "ok", "ok", "ok"],
    "template.create": ["ok", "ok", "ok", 403, "ok", "ok", "ok"],
    "schema.manage":   ["ok", "ok", 403, 403, 403, 403, 403],
    "user.manage":     ["ok", "ok", 403, 403, 403, 403, 403],
    "stats.view":      ["ok", "ok", 403, 403, 403, 403, 403],
}


@pytest.fixture(scope="module")
def people(db, users):
    from tests.http.conftest import _mkuser
    out = dict(users)
    out["cadm"] = _mkuser(db, "acme_company_admin", "company_admin", "acme_001")
    out["rev"] = _mkuser(db, "acme_reviewer", "reviewer", "acme_001")
    out["acme3"] = _mkuser(db, "acme_user3", "client", "acme_001")
    ina = _mkuser(db, "acme_inactive", "client", "acme_001")
    ina.is_active = False
    db.commit()
    out["inactive"] = ina
    return out


@pytest.fixture(scope="module")
def headers(people):
    from app.core.auth import create_access_token
    h = {"anon": {}}
    for name, u in people.items():
        tok = create_access_token({"sub": str(u.id), "role": u.role,
                                   "client_id": u.client_id})
        h[name] = {"Authorization": f"Bearer {tok}"}
    return h


@pytest.fixture(scope="module")
def job(db, people):
    import json
    from app.models.models import DocumentResult, ExtractionJob
    j = ExtractionJob(user_id=people["acme2"].id, client_id="acme_001",
                      status="completed", total_docs=1, successful=1,
                      input_source="upload")
    db.add(j)
    db.commit()
    db.refresh(j)
    d = DocumentResult(job_id=j.id, filename="m.pdf", original_filename="m.pdf",
                       extraction_json=json.dumps({
                           "template_type": "slot", "extracted_fields": {},
                           "extracted_data": {}}))
    db.add(d)
    db.commit()
    db.refresh(d)
    return j, d


def _request(client, group, job, h, pdf_bytes):
    j, d = job
    if group == "job.view":
        return client.get(f"/api/jobs/{j.id}/results", headers=h)
    if group == "job.review":
        return client.post(f"/api/jobs/{j.id}/docs/{d.id}/approve", headers=h)
    if group == "job.export":
        return client.post("/api/export/combined", headers=h,
                           json={"job_id": j.id})
    if group == "job.cancel":
        return client.delete(f"/api/jobs/{j.id}", headers=h)   # completed: 400
    if group == "job.list":
        return client.get("/api/jobs", headers=h)
    if group == "upload":
        # an unsupported file type is refused after the permission check
        return client.post("/api/extract/upload", headers=h,
                           files={"files": ("x.exe", b"MZ", "application/octet-stream")})
    if group == "template.create":
        return client.post("/api/templates", headers=h, json={"name": ""})
    if group == "schema.manage":
        return client.post("/api/schemas", headers=h, json={})
    if group == "user.manage":
        return client.get("/api/admin/users", headers=h)
    if group == "stats.view":
        return client.get("/api/admin/stats", headers=h)
    raise AssertionError(group)


def _cells():
    for group, row in MATRIX.items():
        for who, want in zip(PRINCIPALS, row + ["auth", "auth"]):
            yield group, who, want


@pytest.mark.parametrize("group,who,want", list(_cells()))
def test_matrix(client, headers, job, pdf_bytes, group, who, want):
    r = _request(client, group, job, headers[who], pdf_bytes)
    if want == "ok":
        assert r.status_code not in (401, 403, 404), (group, who, r.status_code, r.text[:200])
    elif want == "auth":
        assert r.status_code in (401, 403), (group, who, r.status_code)
        if r.status_code == 403:
            assert "Not authenticated" in r.text, r.text
    else:
        assert r.status_code == want, (group, who, r.status_code, r.text[:200])


def test_another_firm_cannot_approve(client, headers, job):
    j, d = job
    assert client.post(f"/api/jobs/{j.id}/docs/{d.id}/approve",
                       headers=headers["other"]).status_code == 404


def test_a_reviewer_cannot_edit_or_delete_a_template(client, headers, templates):
    tid = templates["acme_private"].id
    assert client.put(f"/api/templates/{tid}", headers=headers["rev"],
                      json={"name": "x"}).status_code in (403, 404)
    assert client.delete(f"/api/templates/{tid}",
                         headers=headers["rev"]).status_code in (403, 404)


def test_an_admin_can_create_a_reviewer(client, auth):
    r = client.post("/api/admin/users", headers=auth["acme"], json={
        "username": "made_reviewer", "display_name": "R", "password": "secret1",
        "role": "reviewer", "client_id": "acme_001"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "reviewer"


def test_the_role_names_the_permissions_the_ui_shows(client, headers):
    r = client.get("/api/auth/me", headers=headers["rev"])
    assert r.status_code == 200
    perms = set(r.json()["permissions"])
    assert {"job.view", "job.review", "job.export"} <= perms
    assert not perms & {"template.create", "schema.manage", "user.manage",
                        "stats.view", "job.delete"}


class TestRoleOf:
    def test_derivation(self):
        from types import SimpleNamespace as N
        from app.core.permissions import role_of
        assert role_of(N(role="admin", client_id=None)) == "platform_admin"
        assert role_of(N(role="admin", client_id="a")) == "tenant_admin"
        assert role_of(N(role="reviewer", client_id="a")) == "reviewer"
        assert role_of(N(role="company_admin", client_id="a")) == "company_admin"
        assert role_of(N(role="client", client_id="a")) == "user"
        assert role_of(N(role="weird", client_id="a")) == "user"

    def test_inactive_user_can_do_nothing(self):
        from types import SimpleNamespace as N
        from app.core.permissions import can
        assert not can(N(role="admin", client_id=None, is_active=False), "stats.view")
