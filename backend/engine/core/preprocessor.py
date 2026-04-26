"""
DocAgent — Preprocessor
Converts PDFs and images into formats consumable by the LLM.
Strategy:
  1. Try text extraction first (cheaper, faster)
  2. Fall back to image conversion for scanned/image-heavy docs
  3. Always produce both text and image when possible for best accuracy
"""

import io
import base64
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from PIL import Image
import pdfplumber
from pypdf import PdfReader


@dataclass
class ProcessedDocument:
    """Unified representation of a processed document."""
    source_path: str
    filename: str
    file_type: str  # pdf, image
    total_pages: int = 1
    extracted_text: str = ""
    has_meaningful_text: bool = False
    page_images_b64: list[str] = field(default_factory=list)  # base64 encoded images
    page_texts: list[str] = field(default_factory=list)
    processing_notes: str = ""

    @property
    def needs_vision(self) -> bool:
        """Whether this doc needs vision API (image-based extraction)."""
        return not self.has_meaningful_text

    @property
    def preview_text(self) -> str:
        return self.extracted_text[:500] if self.extracted_text else "(no text extracted)"


SUPPORTED_EXTENSIONS = {
    "pdf": "pdf",
    "png": "image", "jpg": "image", "jpeg": "image",
    "tiff": "image", "tif": "image", "bmp": "image",
    "webp": "image", "heic": "image",
}

MIN_TEXT_LENGTH = 50  # Minimum chars to consider text extraction successful


def preprocess_file(file_path: str | Path) -> ProcessedDocument:
    """Main entry point: process any supported file into a ProcessedDocument."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: .{ext}. Supported: {list(SUPPORTED_EXTENSIONS.keys())}")

    file_type = SUPPORTED_EXTENSIONS[ext]

    if file_type == "pdf":
        return _process_pdf(file_path)
    else:
        return _process_image(file_path)


def _process_pdf(file_path: Path) -> ProcessedDocument:
    """Process a PDF file: extract text and convert pages to images."""
    doc = ProcessedDocument(
        source_path=str(file_path),
        filename=file_path.name,
        file_type="pdf",
    )

    # Step 1: Extract text using pdfplumber
    try:
        with pdfplumber.open(file_path) as pdf:
            doc.total_pages = len(pdf.pages)
            for page in pdf.pages:
                text = page.extract_text() or ""
                doc.page_texts.append(text)
            doc.extracted_text = "\n\n--- PAGE BREAK ---\n\n".join(doc.page_texts)
    except Exception as e:
        doc.processing_notes += f"Text extraction failed: {e}. "

    # Determine if text extraction was meaningful
    clean_text = doc.extracted_text.strip()
    doc.has_meaningful_text = len(clean_text) > MIN_TEXT_LENGTH

    # Step 2: Convert pages to images (for vision API or if text extraction was poor)
    try:
        _pdf_pages_to_images(file_path, doc)
    except Exception as e:
        doc.processing_notes += f"Image conversion failed: {e}. "

    if not doc.has_meaningful_text and not doc.page_images_b64:
        doc.processing_notes += "WARNING: Neither text nor images could be extracted. "

    return doc


def _pdf_pages_to_images(file_path: Path, doc: ProcessedDocument):
    """Convert PDF pages to base64 images using pypdf + PIL rendering.
    Falls back to a simple approach without poppler dependency."""
    try:
        # Try pdf2image first (requires poppler)
        from pdf2image import convert_from_path
        images = convert_from_path(
            str(file_path),
            dpi=200,
            fmt="jpeg",
            first_page=1,
            last_page=min(doc.total_pages, 20),  # Cap at 20 pages
        )
        for img in images:
            img = _optimize_image(img)
            b64 = _image_to_base64(img)
            doc.page_images_b64.append(b64)
    except ImportError:
        # Fallback: extract any embedded images from PDF
        doc.processing_notes += "pdf2image not available, using text-only mode. "
    except Exception as e:
        doc.processing_notes += f"pdf2image conversion error: {e}. "


def _process_image(file_path: Path) -> ProcessedDocument:
    """Process an image file."""
    doc = ProcessedDocument(
        source_path=str(file_path),
        filename=file_path.name,
        file_type="image",
        total_pages=1,
        has_meaningful_text=False,
    )

    try:
        img = Image.open(file_path)
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img = _optimize_image(img)
        b64 = _image_to_base64(img)
        doc.page_images_b64.append(b64)
    except Exception as e:
        doc.processing_notes += f"Image processing failed: {e}. "
        raise

    return doc


def _optimize_image(img: Image.Image, max_size: int = 2048) -> Image.Image:
    """Resize and optimize image for API consumption.
    Target: good quality but reasonable file size."""
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        new_size = (int(w * ratio), int(h * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    return img


def _image_to_base64(img: Image.Image, format: str = "JPEG", quality: int = 85) -> str:
    """Convert PIL Image to base64 string."""
    buffer = io.BytesIO()
    img.save(buffer, format=format, quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def get_supported_files(folder: str | Path) -> list[Path]:
    """Scan a folder and return all supported document files."""
    folder = Path(folder)
    if not folder.exists():
        return []

    files = []
    seen = set()
    for ext in SUPPORTED_EXTENSIONS:
        for f in folder.glob(f"*.{ext}"):
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(f)
        for f in folder.glob(f"*.{ext.upper()}"):
            resolved = f.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(f)
    return sorted(files)