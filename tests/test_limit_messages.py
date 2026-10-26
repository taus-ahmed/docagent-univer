"""A refused upload says what was refused, by how much, and what governs it
(Part 3.4 c): the file's own page count / size / pixels, the limit, and the
setting that holds the limit. Defaults are not raised here."""
import io

import pytest
from fastapi import HTTPException

from tests.harness import bootstrap as bs

bs.bootstrap()

from app.config import settings  # noqa: E402
from app.core.storage import get_storage  # noqa: E402
from app.services.uploads import _validate_upload_content  # noqa: E402


def _pdf(pages):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(612, 792)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_the_defaults_are_the_documented_ones():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert (s.MAX_PDF_PAGES, s.MAX_IMAGE_PIXELS, s.MAX_UPLOAD_SIZE_MB) == (200, 50_000_000, 50)


def test_too_many_pages_names_the_file_its_count_and_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "MAX_PDF_PAGES", 2)
    with pytest.raises(HTTPException) as e:
        _validate_upload_content("stack.pdf", _pdf(3))
    d = e.value.detail
    assert "stack.pdf has 3 pages" in d and "2 pages" in d and "MAX_PDF_PAGES" in d


def test_too_many_pixels_names_the_size_and_the_setting(monkeypatch):
    from PIL import Image
    monkeypatch.setattr(settings, "MAX_IMAGE_PIXELS", 10_000)
    buf = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(buf, "PNG")
    with pytest.raises(HTTPException) as e:
        _validate_upload_content("scan.png", buf.getvalue())
    d = e.value.detail
    assert "scan.png is 20,000 pixels" in d and "10,000" in d and "MAX_IMAGE_PIXELS" in d


def test_too_large_names_the_size_and_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    msg = get_storage().validate_upload("big.pdf", 3 * 1024 * 1024)
    assert "3.0 MB" in msg and "1 MB" in msg and "MAX_UPLOAD_SIZE_MB" in msg
