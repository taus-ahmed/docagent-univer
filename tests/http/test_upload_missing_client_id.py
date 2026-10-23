"""Missing super-admin tenant scope is an application-level HTTP 400."""

import io

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


@pytest.mark.parametrize(
    "form_data",
    ({"client_id": ""}, {}),
    ids=("empty-field", "omitted-field"),
)
def test_unscoped_super_admin_without_client_id_has_no_side_effects(
        client, auth, db, pdf_bytes, monkeypatch, form_data):
    """Validation must reach the tenant resolver before creating any work."""
    from app.models.models import ExtractionJob

    before = db.query(ExtractionJob).count()

    def forbidden_save(*_args, **_kwargs):
        pytest.fail("a rejected upload must not be persisted")

    def forbidden_thread(*_args, **_kwargs):
        pytest.fail("a rejected upload must not create a background thread")

    monkeypatch.setattr(
        "app.core.storage.StorageService.save_upload", forbidden_save)
    monkeypatch.setattr(
        "app.api.routes.extract.threading.Thread", forbidden_thread)

    response = client.post(
        "/api/extract/upload",
        headers=auth["super"],
        data=form_data,
        files=[("files", ("doc.pdf", io.BytesIO(pdf_bytes),
                          "application/pdf"))],
    )

    assert response.status_code == 400, response.text
    assert "client_id is required" in response.json()["detail"]
    db.expire_all()
    assert db.query(ExtractionJob).count() == before


def test_tenant_bound_user_may_omit_client_id(
        client, auth, db, pdf_bytes, monkeypatch):
    """The authenticated tenant remains authoritative when the form omits it."""
    import threading

    from app.models.models import ExtractionJob

    saved_for = []

    def capture_save(_storage, _content, _filename, _job_id,
                     client_id=None, **_kwargs):
        saved_for.append(client_id)
        return "test/upload.pdf", "test/upload.pdf"

    class InertThread(threading.Thread):
        def start(self):
            return None

    monkeypatch.setattr(
        "app.core.storage.StorageService.save_upload", capture_save)
    monkeypatch.setattr(
        "app.api.routes.extract.threading.Thread", InertThread)

    response = client.post(
        "/api/extract/upload",
        headers=auth["acme2"],
        data={},
        files=[("files", ("doc.pdf", io.BytesIO(pdf_bytes),
                          "application/pdf"))],
    )

    assert response.status_code == 202, response.text
    db.expire_all()
    job = db.query(ExtractionJob).filter(
        ExtractionJob.id == response.json()["job_id"]).one()
    assert job.client_id == "acme_001"
    assert saved_for == ["acme_001"]
