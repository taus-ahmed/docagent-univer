"""Upload input handling: safe names, page selection, content checks, image normalisation, the streamed upload.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from fastapi import HTTPException
from typing import Optional
from pathlib import Path
from fastapi import UploadFile
from log_safety import exc_brief
import io
import json
import re
from app.config import settings
import warnings
# --imports-end--


_IMAGE_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".bmp",
    ".heic", ".heif", ".gif", ".avif",
})


_UPLOAD_IMAGE_FORMATS = {
    "PNG": ".png",
    "JPEG": ".jpg",
    "TIFF": ".tiff",
}


def _safe_upload_name(filename: str, canonical_suffix: str) -> str:
    """A single safe stored name whose suffix matches the file's content."""
    raw = str(filename or "")
    portable = raw.replace("\\", "/")
    if not raw or portable != Path(portable).name or portable in (".", ".."):
        raise HTTPException(status_code=400, detail="Unsafe upload filename.")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", portable).strip("._-")
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", Path(cleaned).stem).strip("_-")
    if not stem:
        stem = "document"
    return f"{stem[:100]}{canonical_suffix}"


def _unique_upload_name(filename: str, used_names: set[str]) -> str:
    """Return a case-insensitively unique stored name within one batch."""
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    sequence = 2
    while candidate.casefold() in used_names:
        candidate = f"{stem}-{sequence}{suffix}"
        sequence += 1
    used_names.add(candidate.casefold())
    return candidate


def _parse_selected_pages(
    value: Optional[str], page_counts: list[tuple[str, int]],
) -> Optional[list[int]]:
    """Validate a 1-based page list against every document in the batch."""
    if value is None or value == "":
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="selected_pages must be a valid JSON array of integers.")
    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=400,
            detail="selected_pages must be a JSON array of integers.")
    if not parsed:
        raise HTTPException(
            status_code=400, detail="selected_pages cannot be empty.")
    if any(type(page) is not int for page in parsed):
        raise HTTPException(
            status_code=400,
            detail="Every selected page must be an integer.")
    if any(page <= 0 for page in parsed):
        raise HTTPException(
            status_code=400,
            detail="Every selected page must be a positive 1-based number.")

    normalized = list(dict.fromkeys(parsed))
    for filename, page_count in page_counts:
        too_high = next(
            (page for page in normalized if page > page_count), None)
        if too_high is not None:
            raise HTTPException(
                status_code=400,
                detail=(f"Selected page {too_high} is out of range for "
                        f"{filename}; the document has {page_count} page(s)."))
    return normalized


def _validate_upload_content(filename: str, content: bytes) -> tuple[str, str, int]:
    """Validate content before any job, storage write, or worker exists."""
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")

    if content.startswith(b"%PDF-"):
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(content), strict=False)
            if reader.is_encrypted:
                try:
                    decrypted = reader.decrypt("")
                except Exception:
                    decrypted = 0
                if not decrypted:
                    raise HTTPException(
                        status_code=400,
                        detail=("Encrypted or password-protected PDFs are not "
                                "supported."))
            page_count = len(reader.pages)
            for page in reader.pages:
                _ = page.mediabox
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=400,
                                detail="PDF is malformed or truncated.")
        if page_count > settings.MAX_PDF_PAGES:
            raise HTTPException(
                status_code=400,
                detail=(f"PDF has {page_count} pages; maximum is "
                        f"{settings.MAX_PDF_PAGES} pages."))
        return _safe_upload_name(filename, ".pdf"), "pdf", page_count

    image_magic = (
        content.startswith(b"\x89PNG\r\n\x1a\n")
        or content.startswith(b"\xff\xd8\xff")
        or content.startswith((b"II*\x00", b"MM\x00*"))
    )
    if not image_magic:
        raise HTTPException(
            status_code=400,
            detail="File content type is not supported. Allowed: PDF, PNG, JPEG, TIFF.")

    from PIL import Image
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = settings.MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image_format = image.format
                width, height = image.size
                if image_format not in _UPLOAD_IMAGE_FORMATS:
                    raise HTTPException(
                        status_code=400,
                        detail="File content type is not supported. Allowed: PDF, PNG, JPEG, TIFF.")
                if width * height > settings.MAX_IMAGE_PIXELS:
                    raise HTTPException(
                        status_code=400,
                        detail=(f"Image has {width * height} pixels; maximum is "
                                f"{settings.MAX_IMAGE_PIXELS} pixels."))
                image.verify()
    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(
            status_code=400,
            detail=f"Image exceeds the {settings.MAX_IMAGE_PIXELS} pixel limit.")
    except Exception:
        raise HTTPException(status_code=400,
                            detail="Image is malformed or truncated.")
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    return (_safe_upload_name(filename, _UPLOAD_IMAGE_FORMATS[image_format]),
            "image", 1)


def _is_image_file(file_path: Path) -> bool:
    return file_path.suffix.lower() in _IMAGE_EXTENSIONS


def _load_image_as_png_bytes(file_path: Path) -> bytes:
    """Load any supported image (including HEIC) as PNG bytes for vision LLM.
    Falls back to raw bytes if Pillow unavailable."""
    suffix = file_path.suffix.lower().lstrip(".")
    if suffix in {"heic", "heif"}:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            print("[IMAGE] pillow-heif not installed — run: pip install pillow-heif", flush=True)
    try:
        from PIL import Image
        import io as _io
        with Image.open(file_path) as img:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()
    except Exception as exc:
        print(f"[IMAGE] Pillow failed ({exc_brief(exc)}), reading raw bytes", flush=True)
        return file_path.read_bytes()


class _IncomingUpload:
    """A file on its way into an extraction job: a name, and its bytes.

    ONE SOURCE OF FILES, TWO DOORS. The upload endpoint has a multipart
    `UploadFile`; the sample-document endpoint has a path on disk. Everything
    after the bytes - validation, the demo gate, the tenant, the template, the
    job row, storage, the worker thread - must be identical for both, or "the
    sample document goes through the same code path as an upload" is a claim
    rather than a fact. This is the only thing the two doors differ in.

    `read()` MAY BE CALLED MORE THAN ONCE AND GIVES THE SAME BYTES EVERY TIME.
    That is what lets the pipeline validate every file before it writes any of
    them while holding only ONE file's bytes at a time: the validation pass
    reads a file and lets it go, and the save pass reads it again. A list of
    every file's bytes would be simpler and would multiply peak memory by the
    batch size — 100 files is an allowed batch here, and 50MB an allowed file.
    """

    __slots__ = ("filename", "original_filename", "_upload", "_path", "_bytes")

    def __init__(self, filename, upload=None, path=None, content=None):
        self.filename = filename
        self.original_filename = filename
        self._upload = upload
        self._path = path
        self._bytes = content

    @classmethod
    def from_upload(cls, upload: UploadFile):
        return cls(upload.filename, upload=upload)

    @classmethod
    def from_path(cls, path, filename=None):
        path = Path(path)
        return cls(filename or path.name, path=path)

    async def read(self) -> bytes:
        if self._bytes is not None:
            return self._bytes
        if self._upload is not None:
            content = await self._upload.read()
            await self._upload.seek(0)
            return content
        return self._path.read_bytes()
