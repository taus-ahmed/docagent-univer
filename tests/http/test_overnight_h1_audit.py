"""H1 — the audit log: append-only, firm-scoped, never carries contents.

Sign-in (ok and failed), sign-out, user administration, password change,
template create / edit / delete and export download are recorded with the
actor, the time, the target and the outcome. The read endpoint is admin-only
and shows a firm administrator their own firm only (the all-routes isolation
suite scans it too: tests/http/test_tenant_isolation_all_routes.py).
"""

from __future__ import annotations

import json

import pytest


def _events(db, **f):
    from app.models.models import AuditEvent
    db.expire_all()
    q = db.query(AuditEvent)
    for k, v in f.items():
        q = q.filter(getattr(AuditEvent, k) == v)
    return q.order_by(AuditEvent.id).all()


def _login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_sign_in_success_and_failure_are_recorded(client, db, users):
    before_ok = len(_events(db, action="login.ok", actor_id=users["acme2"].id))
    before_bad = len(_events(db, action="login.failed", actor_id=users["acme2"].id))
    assert _login(client, "acme_user", "pw-acme_user").status_code == 200
    assert _login(client, "acme_user", "wrong-password-x").status_code == 401
    ok = _events(db, action="login.ok", actor_id=users["acme2"].id)
    bad = _events(db, action="login.failed", actor_id=users["acme2"].id)
    assert len(ok) == before_ok + 1 and len(bad) == before_bad + 1
    assert bad[-1].outcome == "failed" and bad[-1].client_id == "acme_001"
    assert ok[-1].actor == "acme_user" and ok[-1].target_type == "user"


def test_an_unknown_username_is_never_written(client, db):
    typed = "MyS3cretPassw0rd-typed-in-the-wrong-box"
    assert _login(client, typed, "x").status_code == 401
    from app.models.models import AuditEvent
    db.expire_all()
    blob = json.dumps([{c.name: str(getattr(e, c.name)) for c in AuditEvent.__table__.columns}
                       for e in db.query(AuditEvent).all()])
    assert typed not in blob


def test_logout_and_password_change_are_recorded(client, db, auth, users):
    assert client.post("/api/auth/logout", headers=auth["acme2"]).status_code == 200
    assert _events(db, action="logout", actor_id=users["acme2"].id)


def test_template_create_edit_delete_and_export_are_recorded(client, db, auth, users):
    grid = {"cells": {"0,0": {"value": "Invoice Number", "style": {}}},
            "colWidths": [160], "merges": {}, "repeatRows": []}
    r = client.post("/api/templates", headers=auth["acme"],
                    json={"name": "h1-audit-template", "description": json.dumps(grid),
                          "columns": [{"name": "Invoice Number", "type": "text", "order": 0}]})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    created = _events(db, action="template.create", target_id=str(tid))
    assert created and created[-1].actor_id == users["acme"].id
    client.put(f"/api/templates/{tid}", headers=auth["acme"], json={"name": "h1-renamed"})
    assert _events(db, action="template.update", target_id=str(tid))
    client.delete(f"/api/templates/{tid}", headers=auth["acme"])
    assert _events(db, action="template.delete", target_id=str(tid))


def test_user_administration_is_recorded(client, db, auth, users):
    r = client.post("/api/admin/users", headers=auth["acme"],
                    json={"username": "h1_new_user", "display_name": "H1",
                          "password": "a-long-enough-passphrase-1", "role": "client",
                          "client_id": "acme_001"})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert _events(db, action="user.create", target_id=str(uid))
    client.put(f"/api/admin/users/{uid}", headers=auth["acme"], json={"is_active": False})
    assert _events(db, action="user.disable", target_id=str(uid))
    client.put(f"/api/admin/users/{uid}", headers=auth["acme"],
               json={"password": "another-long-passphrase-2"})
    assert _events(db, action="password.reset", target_id=str(uid))
    client.delete(f"/api/admin/users/{uid}", headers=auth["acme"])
    assert _events(db, action="user.delete", target_id=str(uid))


def test_the_log_is_append_only(db):
    from app.core import audit
    from app.models.models import AuditEvent
    audit.record(db, "logout", client_id="acme_001")
    e = db.query(AuditEvent).order_by(AuditEvent.id.desc()).first()
    e.outcome = "tampered"
    with pytest.raises(RuntimeError, match="append-only"):
        db.commit()
    db.rollback()
    with pytest.raises(RuntimeError, match="append-only"):
        db.delete(db.query(AuditEvent).order_by(AuditEvent.id.desc()).first())
        db.commit()
    db.rollback()


def test_the_read_endpoint_is_admin_only_paged_filtered_and_firm_scoped(client, db, auth):
    from app.core import audit
    audit.record(db, "logout", client_id="other_002")       # another firm's event
    assert client.get("/api/admin/audit", headers=auth["acme2"]).status_code == 403
    r = client.get("/api/admin/audit", headers=auth["acme"],
                   params={"page_size": 2, "client_id": "other_002"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page_size"] == 2 and len(body["events"]) <= 2
    assert all(e["client_id"] == "acme_001" for e in body["events"])
    r2 = client.get("/api/admin/audit", headers=auth["acme"],
                    params={"action": "login.ok"})
    assert all(e["action"] == "login.ok" for e in r2.json()["events"])
    r3 = client.get("/api/admin/audit", headers=auth["super"],
                    params={"client_id": "other_002"})
    assert r3.json()["events"] and all(e["client_id"] == "other_002"
                                       for e in r3.json()["events"])


def test_no_document_contents_or_personal_data_columns():
    from app.models.models import AuditEvent
    cols = {c.name for c in AuditEvent.__table__.columns}
    assert cols == {"id", "at", "client_id", "actor_id", "actor", "action",
                    "target_type", "target_id", "outcome", "request_id"}
