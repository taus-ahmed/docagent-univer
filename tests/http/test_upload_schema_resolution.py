"""Upload schema resolution must never borrow another tenant's schema."""

import io

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def _upload(client, headers, pdf, *, client_id=None):
    data = {} if client_id is None else {"client_id": client_id}
    return client.post(
        "/api/extract/upload", headers=headers, data=data,
        files=[("files", ("doc.pdf", io.BytesIO(pdf), "application/pdf"))],
    )


@pytest.fixture(autouse=True)
def _inert_extraction(monkeypatch):
    import threading

    class InertThread(threading.Thread):
        def start(self):
            return None

    monkeypatch.setattr("app.api.routes.extract.threading.Thread", InertThread)


def test_non_demo_tenant_without_schema_is_refused_without_side_effects(
        client, demo_auth, db, pdf_bytes, monkeypatch):
    from app.models.models import ExtractionJob

    before = db.query(ExtractionJob).count()

    def forbidden_save(*_args, **_kwargs):
        pytest.fail("a schema-less tenant's file must not be persisted")

    def forbidden_thread(*_args, **_kwargs):
        pytest.fail("a schema-less tenant must not start extraction")

    monkeypatch.setattr(
        "app.core.storage.StorageService.save_upload", forbidden_save)
    monkeypatch.setattr(
        "app.api.routes.extract.threading.Thread", forbidden_thread)

    response = _upload(client, demo_auth, pdf_bytes, client_id="demo_001")

    assert response.status_code == 404, response.text
    assert response.json() == {
        "detail": "No extraction schema is configured for this client."
    }
    assert "demo_001" not in response.text
    db.expire_all()
    assert db.query(ExtractionJob).count() == before


def test_tenant_with_own_schema_is_unaffected(client, auth, pdf_bytes):
    response = _upload(client, auth["acme2"], pdf_bytes)
    assert response.status_code == 202, response.text


def test_demo_001_resolves_its_own_schema(client, auth, pdf_bytes):
    response = _upload(
        client, auth["super"], pdf_bytes, client_id="demo_001")
    assert response.status_code == 202, response.text


def test_configured_live_demo_explicitly_uses_demo_schema(
        client, demo_auth, demo_on, pdf_bytes):
    response = _upload(client, demo_auth, pdf_bytes)
    assert response.status_code == 202, response.text
