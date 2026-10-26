"""
Limits cannot be turned against another firm (B3).

The login limiter counts failures per (client IP, username), with the IP the
platform's proxy appended (the LAST X-Forwarded-For entry). The upload limits
(size, pages, pixels, files per batch) are checked per request and hold no
state at all, so one firm hitting them cannot affect another.
"""
from __future__ import annotations

import io
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    from app.api.routes import auth as R
    monkeypatch.setattr(R, "_fail_counts", type(R._fail_counts)(int))
    monkeypatch.setattr(R, "_lockout_until", {})


def _login(client, username, password, xff=None):
    h = {"X-Forwarded-For": xff} if xff else {}
    return client.post("/api/auth/login", headers=h,
                       json={"username": username, "password": password})


def _lock(client, username, xff):
    from app.api.routes.auth import MAX_ATTEMPTS
    for _ in range(MAX_ATTEMPTS):
        assert _login(client, username, "wrong", xff).status_code == 401
    assert _login(client, username, "wrong", xff).status_code == 429


class TestLogin:
    def test_failing_one_username_does_not_lock_another_from_the_same_address(
            self, client, users):
        _lock(client, "other_user", "198.51.100.7")        # firm other_002
        r = _login(client, "acme_user", "pw-acme_user", "198.51.100.7")
        assert r.status_code == 200, r.text                # firm acme_001 unaffected

    def test_a_locked_username_still_signs_in_from_its_own_address(self, client, users):
        _lock(client, "acme_user", "203.0.113.9")           # an attacker's address
        assert _login(client, "acme_user", "pw-acme_user", "192.0.2.44").status_code == 200

    def test_a_spoofed_first_forwarded_entry_cannot_name_the_victim(self, client, users):
        """The attacker sends X-Forwarded-For: <victim>; the proxy appends the
        attacker's real address. Only the real one is locked."""
        _lock(client, "acme_user", "192.0.2.44, 203.0.113.9")
        assert _login(client, "acme_user", "pw-acme_user", "192.0.2.44").status_code == 200

    def test_rotating_the_first_entry_does_not_escape_the_limit(self, client, users):
        from app.api.routes.auth import MAX_ATTEMPTS
        for i in range(MAX_ATTEMPTS):
            _login(client, "acme_user", "wrong", f"10.0.0.{i}, 203.0.113.9")
        assert _login(client, "acme_user", "wrong", "10.9.9.9, 203.0.113.9").status_code == 429

    def test_case_and_spaces_do_not_make_a_new_counter(self, client, users):
        from app.api.routes.auth import MAX_ATTEMPTS
        for i in range(MAX_ATTEMPTS):
            _login(client, " Acme_User " if i % 2 else "acme_user", "wrong", "203.0.113.5")
        assert _login(client, "ACME_USER", "wrong", "203.0.113.5").status_code == 429


class TestUploadLimitsHoldNoState:
    @pytest.fixture(autouse=True)
    def _inert(self, monkeypatch):
        class _T:
            def __init__(self, *a, **k): pass
            def start(self): pass
        monkeypatch.setattr("app.api.routes.extract.threading", SimpleNamespace(Thread=_T))

    def test_one_firm_over_every_limit_leaves_the_other_untouched(
            self, client, auth, monkeypatch, pdf_bytes):
        from app.config import settings
        monkeypatch.setattr(settings, "MAX_PDF_PAGES", 1)
        monkeypatch.setattr(settings, "MAX_FILES_PER_BATCH", 2)
        big = (bs.PDF_DIR / "BS-2024-Q1.pdf").read_bytes()          # 2 pages
        for _ in range(20):
            r = client.post("/api/extract/upload", headers=auth["other"],
                            files=[("files", ("b.pdf", io.BytesIO(big), "application/pdf"))])
            assert r.status_code == 400 and "maximum is 1 pages" in r.text
        r = client.post("/api/extract/upload", headers=auth["other"],
                        files=[("files", (f"{i}.pdf", io.BytesIO(pdf_bytes), "application/pdf"))
                               for i in range(3)])
        assert r.status_code == 400
        r = client.post("/api/extract/upload", headers=auth["acme2"],
                        files=[("files", ("ok.pdf", io.BytesIO(pdf_bytes), "application/pdf"))])
        assert r.status_code == 202, r.text

    def test_the_defaults(self):
        from app.config import Settings
        f = Settings.model_fields
        assert (f["MAX_UPLOAD_SIZE_MB"].default, f["MAX_PDF_PAGES"].default,
                f["MAX_IMAGE_PIXELS"].default, f["MAX_FILES_PER_BATCH"].default,
                f["TENANT_MONTHLY_PAGE_LIMIT"].default) == (50, 200, 50_000_000, 100, 0)
