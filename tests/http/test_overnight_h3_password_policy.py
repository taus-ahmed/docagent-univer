"""H3 — one password policy (12+ characters, not the username, not a common
password or a plain sequence), enforced on create, reset and change, with
clear messages that never echo the password."""

from __future__ import annotations

import pytest

from app.core.password_policy import problems


@pytest.mark.parametrize("pw,user,why", [
    ("short-one", "alice", "at least 12"),
    ("alice_smith_01", "alice_smith_01", "username"),
    ("ALICE_SMITH_01", "alice_smith_01", "username"),
    ("alice_smith_011234", "alice_smith_01", None),
    ("password1234", "bob", "most common"),
    ("Password1234", "bob", "most common"),
    ("123456789012", "bob", "most common"),
    ("aaaaaaaaaaaaaa", "bob", "repeated"),
    ("23456789012345", "bob", "sequence"),
    ("correct horse battery", "bob", None),
])
def test_the_policy(pw, user, why):
    found = " ".join(problems(pw, user)).casefold()
    if why is None:
        assert found == "", found
    else:
        assert why in found, found
        assert pw.casefold() not in found, "the message never echoes the password"


def test_create_refuses_a_weak_password_with_a_clear_message(client, auth):
    r = client.post("/api/admin/users", headers=auth["acme"],
                    json={"username": "h3_weak", "display_name": "x",
                          "password": "password1234", "role": "client",
                          "client_id": "acme_001"})
    assert r.status_code == 400
    assert "most common" in r.json()["detail"]
    ok = client.post("/api/admin/users", headers=auth["acme"],
                     json={"username": "h3_strong", "display_name": "x",
                           "password": "a sound passphrase 42", "role": "client",
                           "client_id": "acme_001"})
    assert ok.status_code == 201, ok.text


def test_reset_refuses_the_username_as_password(client, auth):
    made = client.post("/api/admin/users", headers=auth["acme"],
                       json={"username": "h3_reset_target", "display_name": "x",
                             "password": "another sound passphrase", "role": "client",
                             "client_id": "acme_001"})
    uid = made.json()["id"]
    r = client.put(f"/api/admin/users/{uid}", headers=auth["acme"],
                   json={"password": "h3_reset_target"})
    assert r.status_code == 400 and "username" in r.json()["detail"]


def test_change_refuses_a_short_or_common_password(client):
    from app.core.auth import create_access_token, hash_password
    from app.models.models import User
    import uuid
    sm = client.app.state._sessionmaker
    s = sm()
    name = f"h3_{uuid.uuid4().hex[:6]}"
    u = User(username=name, display_name=name, role="client", client_id="acme_001",
             password_hash=hash_password("the original passphrase"), is_active=True)
    s.add(u)
    s.commit()
    hdr = {"Authorization": "Bearer " + create_access_token(
        {"sub": str(u.id), "role": "client", "client_id": "acme_001", "tv": 0})}
    s.close()
    r = client.post("/api/auth/change-password", headers=hdr,
                    json={"current_password": "the original passphrase",
                          "new_password": "qwerty123456"})
    assert r.status_code == 400 and "most common" in r.json()["detail"]
    r = client.put("/api/auth/me", headers=hdr, json={"password": "tooshort"})
    assert r.status_code == 400 and "at least 12" in r.json()["detail"]
