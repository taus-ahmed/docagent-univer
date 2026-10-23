"""Tenant admins manage users only inside their own tenant boundary."""

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture
def make_user(db, request):
    from app.core.auth import hash_password
    from app.models.models import User

    made = []

    def make(label, *, client_id="acme_001", role="client"):
        user = User(
            username=f"x2_{request.node.name}_{label}"[:50],
            display_name=label,
            password_hash=hash_password("original-password"),
            role=role,
            client_id=client_id,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        made.append(user)
        return user

    yield make

    for user in made:
        db.expire_all()
        current = db.query(User).filter(User.id == user.id).first()
        if current:
            db.delete(current)
    db.commit()


def _create_payload(username, *, role="client", client_id="acme_001"):
    return {
        "username": username,
        "display_name": username,
        "password": "created-password",
        "role": role,
        "client_id": client_id,
    }


def test_tenant_admin_lists_only_own_tenant(client, auth):
    response = client.get("/api/admin/users", headers=auth["acme"])

    assert response.status_code == 200, response.text
    assert response.json()
    assert {row["client_id"] for row in response.json()} == {"acme_001"}


@pytest.mark.parametrize(
    ("role", "client_id"),
    [("client", "other_002"), ("admin", "other_002"), ("admin", None)],
)
def test_tenant_admin_cannot_create_outside_own_tenant(
        client, auth, db, request, role, client_id):
    from app.models.models import User

    username = f"x2_create_{request.node.callspec.id}".replace("-", "_")
    response = client.post(
        "/api/admin/users", headers=auth["acme"],
        json=_create_payload(username, role=role, client_id=client_id),
    )

    assert response.status_code == 403, response.text
    assert db.query(User).filter(User.username == username).first() is None


def test_tenant_admin_can_create_user_and_admin_in_own_tenant(
        client, auth, db):
    from app.models.models import User

    usernames = ["x2_create_own_client", "x2_create_own_admin"]
    try:
        for username, role in zip(usernames, ("client", "admin")):
            response = client.post(
                "/api/admin/users", headers=auth["acme"],
                json=_create_payload(username, role=role),
            )
            assert response.status_code == 201, response.text
            assert response.json()["client_id"] == "acme_001"
            assert response.json()["role"] == role
    finally:
        db.query(User).filter(User.username.in_(usernames)).delete(
            synchronize_session=False)
        db.commit()


@pytest.mark.parametrize("target", ["super", "other"])
def test_other_tenant_and_platform_users_are_not_disclosed_on_update(
        client, auth, users, db, target):
    user = users[target]
    before = (user.display_name, user.password_hash, user.client_id, user.role)

    response = client.put(
        f"/api/admin/users/{user.id}", headers=auth["acme"],
        json={"display_name": "stolen", "password": "stolen-password"},
    )

    assert response.status_code == 404, response.text
    db.refresh(user)
    assert (user.display_name, user.password_hash, user.client_id, user.role) == before


def test_tenant_admin_cannot_reset_super_admin_password(
        client, auth, users, db):
    from app.core.auth import verify_password

    super_admin = users["super"]
    old_hash = super_admin.password_hash
    response = client.put(
        f"/api/admin/users/{super_admin.id}", headers=auth["acme"],
        json={"password": "tenant-takeover"},
    )

    assert response.status_code == 404, response.text
    db.refresh(super_admin)
    assert super_admin.password_hash == old_hash
    assert not verify_password("tenant-takeover", super_admin.password_hash)


def test_tenant_admin_cannot_remove_own_tenant_scope(
        client, auth, users, db):
    admin = users["acme"]
    response = client.put(
        f"/api/admin/users/{admin.id}", headers=auth["acme"],
        json={"client_id": ""},
    )

    assert response.status_code == 400, response.text
    db.refresh(admin)
    assert admin.client_id == "acme_001"


def test_tenant_admin_cannot_change_own_role(client, auth, users, db):
    admin = users["acme"]
    response = client.put(
        f"/api/admin/users/{admin.id}", headers=auth["acme"],
        json={"role": "client"},
    )

    assert response.status_code == 400, response.text
    db.refresh(admin)
    assert admin.role == "admin"


def test_tenant_admin_cannot_change_any_users_client_id(
        client, auth, db, make_user):
    target = make_user("move-target")
    response = client.put(
        f"/api/admin/users/{target.id}", headers=auth["acme"],
        json={"client_id": "other_002"},
    )

    assert response.status_code == 400, response.text
    db.refresh(target)
    assert target.client_id == "acme_001"


def test_tenant_admin_can_update_reset_and_deactivate_own_tenant_user(
        client, auth, db, make_user):
    from app.core.auth import verify_password

    target = make_user("own-target")
    updated = client.put(
        f"/api/admin/users/{target.id}", headers=auth["acme"],
        json={"display_name": "Updated", "password": "new-password",
              "role": "admin"},
    )
    assert updated.status_code == 200, updated.text
    db.refresh(target)
    assert target.display_name == "Updated"
    assert target.role == "admin"
    assert verify_password("new-password", target.password_hash)

    deleted = client.delete(
        f"/api/admin/users/{target.id}", headers=auth["acme"])
    assert deleted.status_code == 200, deleted.text
    db.refresh(target)
    assert target.is_active is False


@pytest.mark.parametrize("target", ["super", "other"])
def test_other_tenant_and_platform_users_are_not_disclosed_on_deactivate(
        client, auth, users, db, target):
    user = users[target]
    response = client.delete(
        f"/api/admin/users/{user.id}", headers=auth["acme"])

    assert response.status_code == 404, response.text
    db.refresh(user)
    assert user.is_active is True


def test_unscoped_super_admin_keeps_cross_tenant_management(
        client, auth, db, make_user):
    target = make_user("super-moves", client_id="other_002")

    listing = client.get("/api/admin/users", headers=auth["super"])
    assert listing.status_code == 200
    assert target.id in {row["id"] for row in listing.json()}

    updated = client.put(
        f"/api/admin/users/{target.id}", headers=auth["super"],
        json={"client_id": "acme_001", "password": "super-reset"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["client_id"] == "acme_001"
