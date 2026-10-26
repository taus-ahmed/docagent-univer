"""HTTP security headers on the API (Part 2.5); no-store kept on /api/."""


def test_api_answers_carry_the_headers_and_no_store(client, auth):
    r = client.get("/api/auth/me", headers=auth["acme2"])
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["cache-control"] == "no-store"
    assert "strict-transport-security" not in h          # development


def test_hsts_only_in_production_over_tls(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ENVIRONMENT", "production", raising=False)
    assert "strict-transport-security" not in client.get("/health").headers
    r = client.get("/health", headers={"X-Forwarded-Proto": "https"})
    assert r.headers["strict-transport-security"].startswith("max-age=")


def test_errors_carry_them_too(client):
    r = client.get("/api/jobs/999999", headers={"Authorization": "Bearer nope"})
    assert r.headers["x-content-type-options"] == "nosniff"
