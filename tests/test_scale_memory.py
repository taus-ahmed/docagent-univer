"""Scale and memory (Part 3.6): OCR page images are kept packed (lossless),
and a process past OCR_MEMORY_LIMIT_MB stops reading pages with a named
failure instead of being killed. Profile figures: docs/OPERATIONS.md §11."""
import contextlib
import io
import sys

from tests.harness import bootstrap as bs

bs.bootstrap()
sys.path.insert(0, str(bs.TESTS_DIR / "fixtures"))
import make_locale_fixtures as M  # noqa: E402
from core.preprocessor import PackedImage, memory_mb, preprocess_file  # noqa: E402


def _page():
    from PIL import Image, ImageDraw
    img = Image.new("L", (1275, 1650), 255)
    d = ImageDraw.Draw(img)
    for y in range(80, 1500, 40):
        d.text((60, y), f"Line {y}: Amount $1,{y:03d}.00", fill=0)
    return img


def test_a_packed_image_is_pixel_identical_and_much_smaller():
    img = _page()
    p = PackedImage(img)
    assert p.size == img.size and p.mode == img.mode
    assert p.tobytes() == img.tobytes()
    assert p.crop((10, 20, 300, 400)).tobytes() == img.crop((10, 20, 300, 400)).tobytes()
    assert p.resize((300, 400)).tobytes() == img.resize((300, 400)).tobytes()
    assert len(p.data) * 10 < len(img.tobytes())


def test_resident_memory_is_readable_here():
    mb = memory_mb()
    assert mb is not None and mb > 1          # /proc on Linux, Win32 on Windows


def _scan(tmp_path):
    d = M.documents()["invoice_us_sales_tax"]
    path = tmp_path / "scan.pdf"
    path.write_bytes(M.scan_pdf(d))
    return path


def test_past_the_memory_limit_a_page_is_a_named_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_WORKERS", "1")
    # the budget is what THIS document adds; any allocation passes 0.01 MB
    monkeypatch.setenv("OCR_MEMORY_LIMIT_MB", "0.01")
    with contextlib.redirect_stdout(io.StringIO()):
        doc = preprocess_file(_scan(tmp_path))
    assert doc.ocr_failed_pages == [1]
    assert "OCR_MEMORY_LIMIT_MB" in doc.processing_notes


def test_the_limit_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_WORKERS", "1")
    monkeypatch.setenv("OCR_MEMORY_LIMIT_MB", "0")
    with contextlib.redirect_stdout(io.StringIO()):
        doc = preprocess_file(_scan(tmp_path))
    assert doc.ocr_failed_pages == [] and doc.ocr_images
    assert isinstance(next(iter(doc.ocr_images.values()))[0], PackedImage)
