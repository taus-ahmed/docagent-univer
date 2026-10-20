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
