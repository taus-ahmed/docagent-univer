"""Watch folders stay inside their tenant (round 12 A1).

`GET /api/watch` listed every tenant's folders to any `role == "admin"`, and
`DELETE /api/watch/{id}` let any admin stop any tenant's folder — so tenant A's
admin saw tenant B's Drive folder ids and could switch B's ingestion off.

Rule now (`drive._visible_watch_folders`):
  * super-admin (admin, no client_id) — every folder, as before;
  * tenant admin (admin with a client_id) — its own tenant's folders only;
  * anyone else — folders they created.
A folder outside that set is a 404 on item routes, so its id does not leak.
"""
import uuid

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture
def folders(db, users):
    from app.core.auth import hash_password
    from app.models.models import User, WatchFolder

    tag = uuid.uuid4().hex[:8]
    other_admin = User(username=f"wf_other_admin_{tag}", display_name="oa",
                       password_hash=hash_password("x"), role="admin",
                       client_id="other_002", is_active=True)
    db.add(other_admin)
    db.commit()
    db.refresh(other_admin)

    def mk(user, client_id, name):
        wf = WatchFolder(user_id=user.id, folder_id=f"{name}-{tag}",
                         folder_name=f"{name}-{tag}", client_id=client_id)
        db.add(wf)
        db.commit()
        db.refresh(wf)
        return wf

    made = {
        "acme_admin": mk(users["acme"], "acme_001", "acme-admin-folder"),
        "acme_user": mk(users["acme2"], "acme_001", "acme-user-folder"),
        "other_user": mk(users["other"], "other_002", "other-user-folder"),
        "other_admin": mk(other_admin, "other_002", "other-admin-folder"),
    }
    yield made, other_admin
    for wf in made.values():
        db.expire_all()
        row = db.query(WatchFolder).filter(WatchFolder.id == wf.id).first()
        if row:
            db.delete(row)
    db.commit()
    row = db.query(User).filter(User.id == other_admin.id).first()
    if row:
        db.delete(row)
    db.commit()


def _token(user):
    from app.core.auth import create_access_token
    tok = create_access_token({"sub": str(user.id), "role": user.role,
                               "client_id": user.client_id})
    return {"Authorization": f"Bearer {tok}"}


def _listed(client, headers, made):
    r = client.get("/api/watch", headers=headers)
    assert r.status_code == 200, r.text
    ids = {row["id"] for row in r.json()}
    return {k for k, wf in made.items() if wf.id in ids}


class TestList:
    def test_tenant_admin_sees_only_its_tenant(self, client, auth, folders):
        made, _ = folders
        assert _listed(client, auth["acme"], made) == {"acme_admin", "acme_user"}

    def test_other_tenant_admin_sees_only_its_tenant(self, client, folders):
        made, other_admin = folders
        assert _listed(client, _token(other_admin), made) == {"other_user", "other_admin"}

    def test_user_sees_only_own(self, client, auth, folders):
        made, _ = folders
        assert _listed(client, auth["acme2"], made) == {"acme_user"}

    def test_super_admin_sees_every_tenant(self, client, auth, folders):
        made, _ = folders
        assert _listed(client, auth["super"], made) == set(made)


class TestDelete:
    def test_tenant_admin_cannot_delete_another_tenants_folder(self, client, auth, folders, db):
        made, _ = folders
        r = client.delete(f"/api/watch/{made['other_user'].id}", headers=auth["acme"])
        assert r.status_code == 404, r.text
        db.expire_all()
        from app.models.models import WatchFolder
        assert db.get(WatchFolder, made["other_user"].id).is_active is True

    def test_tenant_admin_may_delete_its_tenants_folder(self, client, auth, folders):
        made, _ = folders
        r = client.delete(f"/api/watch/{made['acme_user'].id}", headers=auth["acme"])
        assert r.status_code == 200, r.text

    def test_user_cannot_delete_a_colleagues_folder(self, client, auth, folders):
        made, _ = folders
        r = client.delete(f"/api/watch/{made['acme_admin'].id}", headers=auth["acme2"])
        assert r.status_code == 404, r.text

    def test_super_admin_may_delete_any(self, client, auth, folders):
        made, _ = folders
        r = client.delete(f"/api/watch/{made['other_admin'].id}", headers=auth["super"])
        assert r.status_code == 200, r.text

    def test_unknown_id_is_404(self, client, auth, folders):
        r = client.delete("/api/watch/987654321", headers=auth["acme"])
        assert r.status_code == 404


class TestCreate:
    def test_body_client_id_cannot_choose_another_tenant(self, client, auth, monkeypatch, db, tmp_path):
        from app.core import storage as storage_mod
        from app.models.models import WatchFolder
        schema = tmp_path / "s.yaml"
        schema.write_text("x: 1", encoding="utf-8")
        monkeypatch.setattr(storage_mod.get_storage(), "get_schema_path",
                            lambda cid: schema)
        fid = "create-" + uuid.uuid4().hex[:8]
        r = client.post("/api/watch", headers=auth["acme"], json={
            "folder_id": fid, "folder_name": fid, "client_id": "other_002"})
        assert r.status_code == 201, r.text
        assert r.json()["client_id"] == "acme_001"
        row = db.query(WatchFolder).filter(WatchFolder.id == r.json()["id"]).first()
        db.delete(row)
        db.commit()
