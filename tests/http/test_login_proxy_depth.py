"""Which X-Forwarded-For entry the login limiter trusts (Run 15, item 6).

Every entry a proxy did not append is whatever the caller sent. With
TRUSTED_PROXY_COUNT = N proxies in front of the app, the client address is
the entry the FARTHEST trusted proxy appended: the N-th from the right. With
no header, or fewer entries than trusted proxies, the limiter falls back to
the TCP peer — coarse (all callers behind one proxy share it), never
spoofable.
"""
from __future__ import annotations

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    from app.api.routes import auth as R
    monkeypatch.setattr(R, "_fail_counts", type(R._fail_counts)(int))
    monkeypatch.setattr(R, "_lockout_until", {})


def _login(client, xff=None, password="wrong", username="acme_user"):
    h = {"X-Forwarded-For": xff} if xff is not None else {}
    return client.post("/api/auth/login", headers=h,
                       json={"username": username, "password": password})


def test_codex_seven_spoofed_first_entries_reach_429(client, users):
    codes = [_login(client, f"198.51.100.{k}, 203.0.113.9").status_code
             for k in range(7)]
    assert codes == [401] * 5 + [429, 429]


@pytest.mark.parametrize("count,xff,want", [
    (1, "6.6.6.6, 203.0.113.9", "203.0.113.9"),
    (2, "6.6.6.6, 192.0.2.10, 203.0.113.9", "192.0.2.10"),
    (2, "192.0.2.10, 203.0.113.9", "192.0.2.10"),
    (2, "203.0.113.9", "peer"),        # fewer entries than proxies: peer
    (0, "6.6.6.6, 203.0.113.9", "peer"),  # no proxy trusted: header ignored
    (1, "", "peer"),
    (1, None, "peer"),
])
def test_the_trusted_entry(monkeypatch, count, xff, want):
    from types import SimpleNamespace
    from app.api.routes import auth as R
    monkeypatch.setattr(R.settings, "TRUSTED_PROXY_COUNT", count)
    req = SimpleNamespace(headers={} if xff is None else {"X-Forwarded-For": xff},
                          client=SimpleNamespace(host="peer"))
    assert R._get_client_ip(req) == want


def test_two_proxies_rotating_the_spoofed_part_does_not_escape(client, users,
                                                               monkeypatch):
    from app.api.routes import auth as R
    monkeypatch.setattr(R.settings, "TRUSTED_PROXY_COUNT", 2)
    codes = [_login(client, f"10.0.0.{k}, 192.0.2.10, 203.0.113.9").status_code
             for k in range(7)]
    assert codes == [401] * 5 + [429, 429]
    # another client behind the same edge is not locked out
    r = _login(client, "192.0.2.99, 203.0.113.9", password="pw-acme_user")
    assert r.status_code == 200, r.text


def test_no_header_is_keyed_on_the_peer_and_still_limited(client, users):
    codes = [_login(client).status_code for _ in range(6)]
    assert codes[-1] == 429


def test_the_default_is_one_proxy():
    from app.config import Settings
    assert Settings.model_fields["TRUSTED_PROXY_COUNT"].default == 1
