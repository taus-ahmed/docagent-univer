"""/health (liveness) and /ready (readiness), including dependencies down (Part 2.2)."""
import pytest


@pytest.fixture
def real_db(app, monkeypatch):
    import app.models as models
    monkeypatch.setattr(models, "SessionLocal", app.state._sessionmaker)


def test_health_is_liveness_only(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_ready_when_everything_answers(client, real_db, monkeypatch):
    import external_tools
    monkeypatch.setattr(external_tools, "tesseract_version", lambda: "5")
    monkeypatch.setattr(external_tools, "poppler_version", lambda c="pdftoppm": (23, 13))
    r = client.get("/ready")
    assert r.status_code == 200, r.text
    assert set(r.json()["checks"]) == {"database", "storage", "tesseract", "pdftoppm", "migrations"}


@pytest.mark.parametrize("down,check", [("database", "database"), ("tesseract", "tesseract"),
                                        ("pdftoppm", "pdftoppm"), ("storage", "storage"),
                                        ("slow", "pdftoppm")])
def test_a_dependency_down_is_503_with_a_reason_code_only(client, real_db, monkeypatch, down, check):
    import time
    import external_tools
    from app.core import readiness
    monkeypatch.setattr(external_tools, "tesseract_version", lambda: "5")
    monkeypatch.setattr(external_tools, "poppler_version", lambda c="pdftoppm": (23, 13))
    monkeypatch.setattr(readiness, "CHECK_TIMEOUT", 1.0)

    def boom(*a, **k):
        raise RuntimeError("postgresql://user:SECRETPASS@db/x refused")
    if down == "database":
        monkeypatch.setattr(readiness, "check_database", boom)
    elif down == "storage":
        monkeypatch.setattr(readiness, "check_storage", boom)
    elif down == "tesseract":
        monkeypatch.setattr(external_tools, "tesseract_version", boom)
    elif down == "pdftoppm":
        monkeypatch.setattr(external_tools, "poppler_version", boom)
    else:
        monkeypatch.setattr(external_tools, "poppler_version", lambda c="pdftoppm": time.sleep(3))
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"][check].startswith("fail")
    assert "SECRET" not in r.text and "postgresql" not in r.text


def test_a_failed_migration_is_not_ready(client, real_db, app, monkeypatch):
    import external_tools
    monkeypatch.setattr(external_tools, "tesseract_version", lambda: "5")
    monkeypatch.setattr(external_tools, "poppler_version", lambda c="pdftoppm": (23, 13))
    monkeypatch.setattr(app.state, "migrations", {"failed": 1}, raising=False)
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["migrations"] == "fail:migration"
