"""
DocAgent — Preprocessor
Converts PDFs and images into formats consumable by the LLM.
Strategy:
  1. Try text extraction first (cheaper, faster)
  2. Fall back to image conversion for scanned/image-heavy docs
  3. Always produce both text and image when possible for best accuracy
"""

import io
import re
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
    page_images_b64: list[str] = field(default_factory=list)
    page_texts: list[str] = field(default_factory=list)
    processing_notes: str = ""

    @property
    def needs_vision(self) -> bool:
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

MIN_TEXT_LENGTH = 50


def preprocess_file(file_path: str | Path) -> ProcessedDocument:
    """Main entry point: process any supported file into a ProcessedDocument."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = file_path.suffix.lower().lstrip(".")
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: .{ext}. Supported: {list(SUPPORTED_EXTENSIONS.keys())}"
        )

    file_type = SUPPORTED_EXTENSIONS[ext]
    return _process_pdf(file_path) if file_type == "pdf" else _process_image(file_path)


def _fix_cross_page_decimals(text: str) -> str:
    """
    Fix decimal numbers split across page breaks by pdfplumber.

    When a PDF renders "$7,513.03" at the bottom of page 1, pdfplumber may
    return "7513.0" on page 1 and "3" at the top of page 2.
    The page break marker is "--- PAGE BREAK ---".

    Pattern: <number ending in incomplete decimal> ... PAGE BREAK ... <1-2 orphan digits>
    Fix:     merge them into the correct number.

    Examples:
      "7513.0\n\n--- PAGE BREAK ---\n\n3\n" -> "7513.03\n\n--- PAGE BREAK ---\n\n"
      "3117.3\n\n--- PAGE BREAK ---\n\n5\n" -> "3117.35\n\n--- PAGE BREAK ---\n\n"
    """
    # Match: number with partial decimal at end of a page, followed by page break,
    # followed by 1-2 stray digits at the start of the next page
    pattern = (
        r'(\d[\d,]*\.\d{0,2})'          # number ending with incomplete decimal
        r'(\s*\n\n--- PAGE BREAK ---\n\n)'  # page break marker
        r'(\d{1,2})\b'                   # 1-2 orphan digits at start of next page
    )

    def merge(m):
        num_part  = m.group(1).replace(',', '')
        separator = m.group(2)
        orphan    = m.group(3)
        # Only merge if the orphan completes the decimal (not a new number)
        decimal_digits = num_part.split('.')[-1] if '.' in num_part else ''
        if len(decimal_digits) < 2:
            merged = num_part + orphan
            return merged + separator
        return m.group(0)  # don't merge if already complete

    return re.sub(pattern, merge, text)


def _fix_within_page_decimals(text: str) -> str:
    """
    Fix decimal numbers split across lines within a single page.
    Pattern: long number followed by 1-3 stray digits on next line.
    Already existed in original code but moved here for clarity.
    """
    return re.sub(
        r'(\d{4,}\.?\d{0,2})\n(\d{1,2})\n',
        lambda m: (
            m.group(1) + m.group(2) + '\n'
            if len(m.group(1).split('.')[-1]) < 2
            else m.group(0)
        ),
        text
    )


def _process_pdf(file_path: Path) -> ProcessedDocument:
    """Process a PDF file: extract text from ALL pages and convert to images."""
    doc = ProcessedDocument(
        source_path=str(file_path),
        filename=file_path.name,
        file_type="pdf",
    )

    # Step 1: Extract text from ALL pages using pdfplumber
    try:
        with pdfplumber.open(file_path) as pdf:
            doc.total_pages = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                # Fix within-page decimal splits
                text = _fix_within_page_decimals(text)
                doc.page_texts.append(text)
                if text.strip():
                    print(
                        f"[PREPROCESS] page {page_num+1}/{doc.total_pages}: "
                        f"{len(text)} chars extracted",
                        flush=True
                    )
                else:
                    print(
                        f"[PREPROCESS] page {page_num+1}/{doc.total_pages}: "
                        f"no text (scanned/image page)",
                        flush=True
                    )

            # Join all pages with clear separator
            doc.extracted_text = "\n\n--- PAGE BREAK ---\n\n".join(doc.page_texts)

            # Fix cross-page decimal splits AFTER joining all pages
            doc.extracted_text = _fix_cross_page_decimals(doc.extracted_text)

    except Exception as e:
        doc.processing_notes += f"Text extraction failed: {e}. "

    # Determine if text extraction was meaningful
    clean_text = doc.extracted_text.strip()
    doc.has_meaningful_text = len(clean_text) > MIN_TEXT_LENGTH

    # Step 2: Convert pages to images (for vision or scanned docs)
    try:
        _pdf_pages_to_images(file_path, doc)
    except Exception as e:
        doc.processing_notes += f"Image conversion failed: {e}. "

    if not doc.has_meaningful_text and not doc.page_images_b64:
        doc.processing_notes += "WARNING: Neither text nor images could be extracted. "

    print(
        f"[PREPROCESS] {file_path.name}: {doc.total_pages} pages, "
        f"{len(doc.extracted_text)} chars total, "
        f"{len(doc.page_images_b64)} images",
        flush=True
    )

    return doc


def _pdf_pages_to_images(file_path: Path, doc: ProcessedDocument):
    """Convert PDF pages to base64 images."""
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(
            str(file_path),
            dpi=200,
            fmt="jpeg",
            first_page=1,
            last_page=min(doc.total_pages, 20),
        )
        for img in images:
            img = _optimize_image(img)
            doc.page_images_b64.append(_image_to_base64(img))
    except ImportError:
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
        doc.page_images_b64.append(_image_to_base64(img))
    except Exception as e:
        doc.processing_notes += f"Image processing failed: {e}. "
        raise

    return doc


def _optimize_image(img: Image.Image, max_size: int = 2048) -> Image.Image:
    """Resize and optimize image for API consumption."""
    w, h = img.size
    if max(w, h) > max_size:
        ratio = max_size / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
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
