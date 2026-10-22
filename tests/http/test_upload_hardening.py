"""Hostile uploads are rejected before jobs, storage, or worker threads."""

import io
import struct
import zlib

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def _post(client, auth, name, content, mime="application/octet-stream"):
    return client.post(
        "/api/extract/upload", headers=auth["acme"],
        data={"client_id": "acme_001"},
        files=[("files", (name, io.BytesIO(content), mime))],
    )


def _guard_side_effects(monkeypatch):
    saved = []
    threaded = []

    def capture_save(_storage, _content, filename, _job_id, **_kwargs):
        saved.append(filename)
        return f"test/{filename}", f"test/{filename}"

    class CapturedThread:
        def __init__(self, *_args, **_kwargs):
            threaded.append("constructed")

        def start(self):
            threaded.append("started")

    monkeypatch.setattr(
        "app.core.storage.StorageService.save_upload", capture_save)
    monkeypatch.setattr(
        "app.api.routes.extract.threading.Thread", CapturedThread)
    return saved, threaded


def _assert_rejected(client, auth, db, monkeypatch, name, content,
                     message, mime="application/octet-stream"):
    from app.models.models import ExtractionJob

    before = db.query(ExtractionJob).count()
    saved, threaded = _guard_side_effects(monkeypatch)
    response = _post(client, auth, name, content, mime)

    assert 400 <= response.status_code < 500, response.text
    assert message.casefold() in response.json()["detail"].casefold()
    assert "traceback" not in response.text.casefold()
    assert str(bs.REPO_DIR).casefold() not in response.text.casefold()
    db.expire_all()
    assert db.query(ExtractionJob).count() == before
    assert saved == []
    assert threaded == []


def _png_with_dimensions(width, height):
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (1, 1), "white").save(out, "PNG")
    data = bytearray(out.getvalue())
    data[16:24] = struct.pack(">II", width, height)
    data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]) & 0xFFFFFFFF)
    return bytes(data)


def _pdf_with_pages(count):
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=72, height=72)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _encrypted_pdf(user_password="secret", owner_password=None):
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(user_password, owner_password=owner_password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_oversized_file_is_rejected_before_side_effects(
        client, auth, db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    content = b"%PDF-1.4\n" + b"0" * (1024 * 1024)
    _assert_rejected(client, auth, db, monkeypatch, "large.pdf", content,
                     "too large", "application/pdf")


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("empty.pdf", b"", "empty"),
        ("fake.pdf", b"plain text pretending to be a PDF", "supported"),
        ("truncated.pdf", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog", "malformed"),
    ],
)
def test_empty_wrong_content_and_truncated_files_are_rejected(
        client, auth, db, monkeypatch, name, content, message):
    _assert_rejected(client, auth, db, monkeypatch, name, content, message)


def test_path_traversal_filename_is_rejected_before_side_effects(
        client, auth, db, monkeypatch, pdf_bytes):
    _assert_rejected(client, auth, db, monkeypatch, "../../secret.pdf",
                     pdf_bytes, "filename", "application/pdf")


def test_decompression_bomb_image_is_rejected_before_side_effects(
        client, auth, db, monkeypatch):
    content = _png_with_dimensions(20_000, 20_000)
    _assert_rejected(client, auth, db, monkeypatch, "bomb.png", content,
                     "pixel", "image/png")


def test_pdf_over_page_limit_is_rejected_before_side_effects(
        client, auth, db, monkeypatch):
    _assert_rejected(client, auth, db, monkeypatch, "long.pdf",
                     _pdf_with_pages(201), "pages", "application/pdf")


def test_encrypted_pdf_is_rejected_before_side_effects(
        client, auth, db, monkeypatch):
    _assert_rejected(client, auth, db, monkeypatch, "locked.pdf",
                     _encrypted_pdf(), "encrypted", "application/pdf")


def test_owner_password_only_pdf_is_accepted(client, auth, monkeypatch):
    saved, threaded = _guard_side_effects(monkeypatch)
    response = _post(
        client, auth, "bank-issued.pdf",
        _encrypted_pdf(user_password="", owner_password="owner-secret"),
        "application/pdf",
    )

    assert response.status_code == 202, response.text
    assert saved == ["bank-issued.pdf"]
    assert threaded == ["constructed", "started"]


def test_colliding_names_are_unique_and_original_names_reach_worker(
        client, auth, db, monkeypatch, pdf_bytes):
    from app.models.models import ExtractionJob

    originals = ["Cheque #1.pdf", "Cheque @1.pdf", "scan.PDF", "scan.pdf"]
    originals += ["\u94f6\u884c.pdf"] * 46
    saved = []
    worker = {}

    def capture_save(_storage, _content, filename, _job_id, **_kwargs):
        saved.append(filename)
        return f"test/{filename}", f"test/{filename}"

    class CapturedThread:
        def __init__(self, *, target, args, kwargs, daemon):
            worker.update(target=target, args=args, kwargs=kwargs, daemon=daemon)

        def start(self):
            worker["started"] = True

    monkeypatch.setattr(
        "app.core.storage.StorageService.save_upload", capture_save)
    monkeypatch.setattr(
        "app.api.routes.extract.threading.Thread", CapturedThread)
    before = db.query(ExtractionJob).count()

    response = client.post(
        "/api/extract/upload",
        headers=auth["acme"],
        data={"client_id": "acme_001"},
        files=[("files", (name, pdf_bytes, "application/pdf"))
               for name in originals],
    )

    assert response.status_code == 202, response.text
    assert response.json()["total_files"] == 50
    assert len(saved) == len(set(name.casefold() for name in saved)) == 50
    assert len(worker["args"][1]) == 50
    assert worker["kwargs"]["original_filenames"] == originals
    assert worker["started"] is True
    db.expire_all()
    jobs = db.query(ExtractionJob).all()
    assert len(jobs) == before + 1
    assert jobs[-1].total_docs == 50


@pytest.mark.parametrize("declared_name", ["renamed.pdf", "renamed.bin"])
def test_png_content_wins_over_filename(
        client, auth, db, monkeypatch, png_bytes, declared_name):
    saved, threaded = _guard_side_effects(monkeypatch)
    response = _post(client, auth, declared_name, png_bytes, "application/pdf")
    assert response.status_code == 202, response.text
    assert saved == ["renamed.png"]
    assert threaded == ["constructed", "started"]


def test_pdf_content_wins_over_png_filename(
        client, auth, db, monkeypatch, pdf_bytes):
    saved, threaded = _guard_side_effects(monkeypatch)
    response = _post(client, auth, "renamed.png", pdf_bytes, "image/png")
    assert response.status_code == 202, response.text
    assert saved == ["renamed.pdf"]
    assert threaded == ["constructed", "started"]


def test_existing_upload_fixture_documents_remain_valid(
        client, auth, monkeypatch):
    from tests.http.test_batch_end_to_end import MIXED, STATEMENTS

    paths = {bs.PDF_DIR / f"{stem}.pdf" for stem in (*MIXED, *STATEMENTS)}
    paths.add(bs.TESTS_DIR / "test_OCR" / "chk_003_clean.png")
    files = [("files", (path.name, path.read_bytes(),
                         "application/octet-stream"))
             for path in sorted(paths)]
    saved, threaded = _guard_side_effects(monkeypatch)

    response = client.post(
        "/api/extract/upload", headers=auth["acme"],
        data={"client_id": "acme_001"}, files=files)

    assert response.status_code == 202, response.text
    assert len(saved) == len(paths)
    assert threaded == ["constructed", "started"]


@pytest.mark.parametrize(
    ("field", "bad_value", "default"),
    [
        ("MAX_UPLOAD_SIZE_MB", "not-a-number", 50),
        ("MAX_PDF_PAGES", "0", 200),
        ("MAX_IMAGE_PIXELS", "-12", 50_000_000),
    ],
)
def test_invalid_limit_values_fall_back_safely(field, bad_value, default):
    from app.config import Settings

    configured = Settings(_env_file=None, **{field: bad_value})
    assert getattr(configured, field) == default
