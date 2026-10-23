"""Page selections fail at the upload boundary, before any side effect."""

import io
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def _two_page_pdf():
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _post(client, auth, selected_pages):
    return client.post(
        "/api/extract/upload",
        headers=auth["acme"],
        data={"client_id": "acme_001", "selected_pages": selected_pages},
        files=[("files", ("two-pages.pdf", _two_page_pdf(),
                           "application/pdf"))],
    )


def _forbid_side_effects(monkeypatch):
    def forbidden_save(*_args, **_kwargs):
        pytest.fail("invalid selected_pages reached storage")

    class ForbiddenThread:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("invalid selected_pages constructed a worker")

    monkeypatch.setattr(
        "app.core.storage.StorageService.save_upload", forbidden_save)
    monkeypatch.setattr(
        "app.api.routes.extract.threading.Thread", ForbiddenThread)


@pytest.mark.parametrize(
    ("selected_pages", "message"),
    [
        (json.dumps(["1"]), "integer"),
        (json.dumps([1.0]), "integer"),
        (json.dumps([True]), "integer"),
        (json.dumps([0]), "positive"),
        (json.dumps([-1]), "positive"),
        (json.dumps([]), "empty"),
        (json.dumps({"page": 1}), "array"),
        ("not-json", "json"),
        (json.dumps([999]), "2 page"),
    ],
)
def test_invalid_selected_pages_are_rejected_before_side_effects(
        client, auth, db, monkeypatch, selected_pages, message):
    from app.models.models import ExtractionJob

    before = db.query(ExtractionJob).count()
    _forbid_side_effects(monkeypatch)

    response = _post(client, auth, selected_pages)

    assert response.status_code == 400, response.text
    assert message in response.json()["detail"].casefold()
    db.expire_all()
    assert db.query(ExtractionJob).count() == before


def test_duplicate_pages_are_normalized_before_worker(
        client, auth, monkeypatch):
    captured = {}

    def capture_save(_storage, _content, filename, _job_id, **_kwargs):
        return f"test/{filename}", f"test/{filename}"

    class CapturedThread:
        def __init__(self, *, kwargs, **_rest):
            captured.update(kwargs)

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(
        "app.core.storage.StorageService.save_upload", capture_save)
    monkeypatch.setattr(
        "app.api.routes.extract.threading.Thread", CapturedThread)

    response = _post(client, auth, json.dumps([2, 1, 2, 1]))

    assert response.status_code == 202, response.text
    assert captured["selected_pages"] == [2, 1]
    assert captured["started"] is True
