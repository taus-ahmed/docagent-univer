"""A tenant check needs a tenant (round 12 A1 scan).

Several checks compare `template.client_id == current_user.client_id`. Both
columns are nullable, and a super-admin's templates (system defaults among
them) carry `client_id = None`, so an account with NO tenant that is not a
super-admin — a `company_admin` or `client` created without a client_id —
matched every one of them: it could edit and delete the system default every
tenant uses, and see every super-admin's shared template. `None` is "no
tenant", not a tenant shared with everyone else who has none.
"""
import json
import uuid

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

GRID = json.dumps({"cells": {"0,0": {"value": "Total", "style": {}}},
                   "colWidths": [160, 160], "merges": {}, "repeatRows": []})


@pytest.fixture
def tenantless(db, users):
    from app.core.auth import create_access_token, hash_password
    from app.models.models import ColumnTemplate, User
    tag = uuid.uuid4().hex[:8]
    made = []
    out = {}
    for role in ("company_admin", "client"):
        u = User(username=f"nt_{role}_{tag}", display_name=role,
                 password_hash=hash_password("x"), role=role,
                 client_id=None, is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        made.append(u)
        tok = create_access_token({"sub": str(u.id), "role": u.role, "client_id": None})
        out[role] = {"Authorization": f"Bearer {tok}"}
    shared = ColumnTemplate(name=f"super_shared_{tag}", document_type="sales_invoice",
                            description=GRID, columns_json="[]",
                            user_id=users["super"].id, client_id=None,
                            is_shared=True, is_default=False)
    db.add(shared)
    db.commit()
    db.refresh(shared)
    yield out, shared
    db.expire_all()
    for obj in [shared, *made]:
        row = db.get(type(obj), obj.id)
        if row:
            db.delete(row)
    db.commit()


def test_tenantless_company_admin_cannot_edit_the_system_default(client, templates, tenantless):
    hdr, _ = tenantless
    tid = templates["system_default"].id
    r = client.put(f"/api/templates/{tid}", headers=hdr["company_admin"],
                   json={"name": "hijacked"})
    assert r.status_code == 403, r.text


def test_tenantless_company_admin_cannot_delete_the_system_default(client, templates, tenantless):
    hdr, _ = tenantless
    r = client.delete(f"/api/templates/{templates['system_default'].id}",
                      headers=hdr["company_admin"])
    assert r.status_code == 403, r.text


@pytest.mark.parametrize("role", ["company_admin", "client"])
def test_tenantless_user_does_not_see_a_super_admins_shared_template(client, tenantless, role):
    hdr, shared = tenantless
    r = client.get(f"/api/templates/{shared.id}", headers=hdr[role])
    assert r.status_code == 403, r.text
    listed = client.get("/api/templates", headers=hdr[role])
    assert listed.status_code == 200
    assert shared.id not in {t["id"] for t in listed.json()}


def test_tenant_member_still_sees_its_own_shared_template(client, auth, templates):
    r = client.get(f"/api/templates/{templates['acme_shared'].id}", headers=auth["acme2"])
    assert r.status_code == 200, r.text


def test_load_template_for_user_needs_a_tenant(db, tenantless):
    from fastapi import HTTPException
    from app.api.routes.extract import load_template_for_user
    from app.models.models import User
    hdr, shared = tenantless
    user = db.query(User).filter(User.role == "client", User.client_id.is_(None),
                                 User.username.like("nt_client_%")).first()
    with pytest.raises(HTTPException) as e:
        load_template_for_user(db, shared.id, user)
    assert e.value.status_code == 403
