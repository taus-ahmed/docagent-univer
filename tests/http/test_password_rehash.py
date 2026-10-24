"""Password hashing: bcrypt, with legacy hashes upgraded on login (X3).

The stored scheme was one round of salted SHA-256 (`salt:hex`) — fast to
brute-force from a leaked table. New hashes are bcrypt over a SHA-256
pre-hash (`bcrypt-sha256$<bcrypt>`, so a password over bcrypt's 72-byte
limit is neither truncated nor rejected). An existing `salt:hex` hash still
verifies — compared in constant time — and is replaced with a bcrypt hash
on the first successful login, in the login's own commit. No migration.
"""
from __future__ import annotations

import hashlib
import secrets

import pytest

from app.core import auth as A


def _legacy(pw: str) -> str:
    salt = secrets.token_hex(16)
    return f"{salt}:{hashlib.sha256((salt + pw).encode()).hexdigest()}"


class TestScheme:
    def test_new_hashes_are_bcrypt(self):
        h = A.hash_password("correct horse")
        assert h.startswith("bcrypt-sha256$$2b$")
        assert A.verify_password("correct horse", h)
        assert not A.verify_password("wrong horse", h)
        assert not A.needs_rehash(h)

    def test_a_legacy_hash_still_verifies_and_needs_rehash(self):
        h = _legacy("s3cret")
        assert A.verify_password("s3cret", h)
        assert not A.verify_password("s3creT", h)
        assert A.needs_rehash(h)

    def test_long_passwords_are_not_truncated(self):
        base = "x" * 80
        h = A.hash_password(base + "A")
        assert A.verify_password(base + "A", h)
        assert not A.verify_password(base + "B", h)

    @pytest.mark.parametrize("stored", ["", "garbage", "a:b:c", "bcrypt-sha256$nope", None])
    def test_malformed_hashes_never_verify(self, stored):
        assert not A.verify_password("anything", stored)

    def test_the_legacy_compare_is_constant_time(self, monkeypatch):
        calls = []
        real = A.hmac.compare_digest
        monkeypatch.setattr(A.hmac, "compare_digest",
                            lambda a, b: calls.append(1) or real(a, b))
        A.verify_password("pw", _legacy("pw"))
        assert calls


class TestUpgradeOnLogin:
    def _user(self, db, pw_hash):
        from app.models.models import User
        # The scratch database is shared by the session: a name of its own.
        u = User(username="legacy-" + secrets.token_hex(4), display_name="Legacy",
                 password_hash=pw_hash, role="client", client_id="acme", is_active=True)
        db.add(u)
        db.commit()
        return u

    def test_a_legacy_hash_is_upgraded_by_a_successful_login(self, client, db):
        u = self._user(db, _legacy("pw-legacy"))
        r = client.post("/api/auth/login",
                        json={"username": u.username, "password": "pw-legacy"})
        assert r.status_code == 200, r.text
        db.refresh(u)
        assert u.password_hash.startswith("bcrypt-sha256$")
        assert A.verify_password("pw-legacy", u.password_hash)
        # and the upgraded hash logs in again
        r = client.post("/api/auth/login",
                        json={"username": u.username, "password": "pw-legacy"})
        assert r.status_code == 200, r.text

    def test_a_failed_login_changes_nothing(self, client, db):
        old = _legacy("pw-legacy")
        u = self._user(db, old)
        r = client.post("/api/auth/login",
                        json={"username": u.username, "password": "nope"})
        assert r.status_code == 401
        db.refresh(u)
        assert u.password_hash == old
