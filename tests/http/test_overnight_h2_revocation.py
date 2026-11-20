"""H2 — token revocation. A per-user token version is checked on every
request; disabling a user, changing or resetting a password and "log out
everywhere" invalidate every older token at once."""

from __future__ import annotations

import pytest


@pytest.fixture
def person(db):
    """A fresh account per test, so revocations never leak into the shared
    session-scoped users the rest of the suite signs in as."""
    import uuid
    from app.core.auth import hash_password
    from app.models.models import User
    name = f"h2_{uuid.uuid4().hex[:8]}"
    u = User(username=name, display_name=name,
             password_hash=hash_password("first-passphrase-123"),
             role="client", client_id="acme_001", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client, user, password="first-passphrase-123"):
    r = client.post("/api/auth/login", json={"username": user.username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _me(client, hdr):
    return client.get("/api/auth/me", headers=hdr).status_code


def test_log_out_everywhere_ends_every_session(client, person):
    a, b = _login(client, person), _login(client, person)
    assert _me(client, a) == 200 and _me(client, b) == 200
    assert client.post("/api/auth/logout-everywhere", headers=a).status_code == 200
    assert _me(client, a) == 401 and _me(client, b) == 401
    assert _me(client, _login(client, person)) == 200          # a new sign-in works


def test_changing_the_password_ends_other_sessions_but_keeps_this_device(client, person):
    other = _login(client, person)
    mine = _login(client, person)
    r = client.post("/api/auth/change-password", headers=mine,
                    json={"current_password": "first-passphrase-123",
                          "new_password": "second-passphrase-456"})
    assert r.status_code == 200, r.text
    assert _me(client, other) == 401 and _me(client, mine) == 401
    fresh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert _me(client, fresh) == 200


def test_an_admin_reset_or_disable_ends_the_users_sessions(client, auth, person):
    hdr = _login(client, person)
    r = client.put(f"/api/admin/users/{person.id}", headers=auth["acme"],
                   json={"password": "reset-passphrase-789"})
    assert r.status_code == 200, r.text
    assert _me(client, hdr) == 401
    hdr = _login(client, person, "reset-passphrase-789")
    client.put(f"/api/admin/users/{person.id}", headers=auth["acme"], json={"is_active": False})
    client.put(f"/api/admin/users/{person.id}", headers=auth["acme"], json={"is_active": True})
    assert _me(client, hdr) == 401, "re-enabling must not revive a disabled user's token"


def test_a_token_without_a_version_is_version_zero(client, db, person):
    from app.core.auth import create_access_token
    tok = create_access_token({"sub": str(person.id), "role": person.role,
                               "client_id": person.client_id})
    assert _me(client, {"Authorization": f"Bearer {tok}"}) == 200
    person.token_version = 1
    db.commit()
    assert _me(client, {"Authorization": f"Bearer {tok}"}) == 401
