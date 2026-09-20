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

from text_layer import SHARD_SHRED, acroform_widgets, read_page


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
    # Positional evidence: one list of words per page, each carrying x0/x1/top,
    # grouped into visual lines. This is what lets validation ask which COLUMN
    # a value sits in — a flat string cannot be asked that. See
    # engine/text_layer.py.
    page_lines: list[list] = field(default_factory=list)
    text_repairs: list[tuple] = field(default_factory=list)
    #: 1-based page numbers whose text layer was SHREDDED — several texts set
    #: at different font sizes over one band of y, their characters interleaved
    #: in x. Separated and rebuilt by `read_page`; listed here so the warning
    #: survives past the log line. NOT a scanned-page signal (I10).
    shredded_pages: list[int] = field(default_factory=list)
    #: 1-based page numbers on which OVERPRINT DETECTION WAS NOT PERFORMED,
    #: because the reader that produced them does not declare
    #: CHARACTER_GEOMETRY (engine/text_layer.py). NOT a claim that those pages
    #: are clean — the check did not run. An empty list means every page was
    #: checked, so the field reads correctly on documents processed before it
    #: existed.
    #:
    #: ⚠ The per-word `overprinted` flag stays TWO-VALUED. A third per-word
    #: value would be swallowed by `overprinted_value`'s negation or would fire
    #: `slot_extractor`'s demotion on every value in the document; the fact
    #: that the check never ran belongs here instead.
    unchecked_overprint_pages: list[int] = field(default_factory=list)
    #: 1-based page numbers on which the SHREDDED-LAYER CHECK WAS NOT
    #: PERFORMED, because the reader cannot tokenise the same page twice (once
    #: size-aware, once size-blind) and `shard_ratio` is the ratio between
    #: those two readings. Again: not a clean result, an absent one.
    unchecked_shred_pages: list[int] = field(default_factory=list)
    #: 1-based page numbers whose text did NOT come from the PDF's own text
    #: layer but from OCR of a rendered image, each with what straightening was
    #: applied: {"page": n, "rotated": deg, "deskewed": deg, "words": n}. A
    #: machine-read page is not the document's own words, and the reader that
    #: produced it declares no capabilities, so this list is what stops "we
    #: OCR'd it" from being invisible downstream.
    ocr_pages: list[dict] = field(default_factory=list)
    #: Pages with no text layer that could NOT be OCR'd (no binary, no render).
    #: Absent and said out loud, rather than an empty page nobody explains.
    ocr_failed_pages: list[int] = field(default_factory=list)
    #: Characters the PDF's OWN text layer yielded, before any OCR. Kept apart
    #: from `extracted_text` because `has_meaningful_text` decides the document
    #: type, and a document typed `digital_pdf` on the strength of text a
    #: machine read off a picture would claim `high` confidence for values no
    #: text layer ever witnessed.
    native_text_chars: int = 0
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


def _ocr_page(file_path: Path, page_number: int, doc: "ProcessedDocument",
              stats: dict):
    """(text, lines, repairs) for a page with no text layer, read by OCR.

    THROUGH THE SEAM, NOT AROUND IT. `read_page` takes a `PageSource`, so the
    OCR reader is handed to the same function the pdfplumber reader goes
    through: wrapped-value repair, page stamping and the capability gates all
    run exactly as they do for a digital page, and the gates SKIP loudly
    because `OcrPageSource` declares nothing.

    A failure here is recorded, never swallowed: a page that could not be OCR'd
    is listed in `ocr_failed_pages` and comes back as empty as it was before,
    which is the honest answer — but a named one.
    """
    try:
        from ocr_source import OcrPageSource, OCR_DPI, render_pdf_page
        image = render_pdf_page(file_path, page_number, dpi=OCR_DPI)
        if image is None:
            raise RuntimeError("the page could not be rendered")
        source = OcrPageSource(image, page_number=page_number, dpi=OCR_DPI)
        text, lines, repairs = read_page(source, stats=stats)
    except Exception as exc:
        doc.ocr_failed_pages.append(page_number)
        doc.processing_notes += (
            f"page {page_number} has no text layer and could not be OCR'd "
            f"({type(exc).__name__}: {exc}). ")
        print(f"[OCR] page {page_number}: NO TEXT LAYER and OCR unavailable — "
              f"{type(exc).__name__}: {exc}", flush=True)
        return "", [], []

    doc.ocr_pages.append({"page": page_number, "words": sum(len(ln) for ln in lines),
                          **source.applied})
    print(f"[OCR] page {page_number}: no text layer — read by Tesseract at "
          f"{OCR_DPI}dpi, rotated {source.applied['rotated']}deg, deskewed "
          f"{source.applied['deskewed']}deg, {len(text)} chars, "
          f"{sum(len(ln) for ln in lines)} words. These are a MACHINE's "
          f"reading, not the document's own text.", flush=True)
    return text, lines, repairs


def _process_pdf(file_path: Path) -> ProcessedDocument:
    """Process a PDF file: extract text from ALL pages and convert to images."""
    doc = ProcessedDocument(
        source_path=str(file_path),
        filename=file_path.name,
        file_type="pdf",
    )

    # Step 1: Extract text from ALL pages using pdfplumber
    try:
        native_chars = 0
        with pdfplumber.open(file_path) as pdf:
            doc.total_pages = len(pdf.pages)
            # A fillable form's checkboxes are widget annotations carrying no
            # text at all, so the selection state — the whole content of the
            # field — never reaches the model. It is in the file; read it.
            widgets = acroform_widgets(file_path)
            if widgets:
                print(f"[TEXTLAYER] {sum(len(v) for v in widgets.values())} "
                      f"form checkbox(es) found — writing their state into "
                      f"the text", flush=True)
            for page_num, page in enumerate(pdf.pages):
                # Read the page WITH its geometry. A page whose values the PDF
                # wrapped inside a table cell comes back reassembled; a page
                # that needed nothing comes back exactly as extract_text()
                # produced it, so the prompt for an untouched document does
                # not change.
                stats = {}
                text, lines, repairs = read_page(page, widgets.get(page_num) or [],
                                                 stats=stats)
                native_chars += len((text or "").strip())
                # A PAGE WITH NO TEXT LAYER IS NOT A PAGE WITH NOTHING ON IT.
                # pdfplumber returns nothing for a scan, and everything
                # downstream — the prompt, grounding, placement, row identity —
                # then has nothing to work with and says so only by being
                # empty. Render it and read it with OCR instead, through the
                # SAME seam: `read_page` takes a PageSource, so nothing below
                # this line learns that a different reader ran.
                if len((text or "").strip()) < MIN_TEXT_LENGTH:
                    text, lines, repairs = _ocr_page(
                        file_path, page_num + 1, doc, stats)
                doc.page_lines.append(lines)
                # I10 — SHREDDED TEXT LAYER, said BEFORE the model is asked.
                # Several texts set at different sizes over one band of y have
                # their characters interleaved in x, and a size-blind reading
                # shatters all of them. `read_page` now separates them; this
                # says that it had to, because a page that needed separating is
                # a page worth checking by hand.
                #
                # ⚠ THIS DOES NOT DETECT A SCANNED DOCUMENT. A thin OCR text
                # layer scores 1.00 here — `round2/bank-statement-sample.pdf` is
                # 108 words over 66 images and looks perfectly clean by this
                # measure. Two different failures, two different signals, and
                # treating this one as the OCR canary would give false
                # assurance.
                #
                # A reader that cannot perform the two-pass comparison at all
                # is recorded as UNCHECKED rather than passing the test it was
                # never able to sit. `stats` carries no `shard_ratio` in that
                # case, and defaulting it to 1.0 here would read as a clean
                # page.
                if stats.get("shard_checked", True) is False:
                    doc.unchecked_shred_pages.append(page_num + 1)
                elif stats.get("shard_ratio", 1.0) >= SHARD_SHRED:
                    doc.shredded_pages.append(page_num + 1)
                    print(
                        f"[TEXTLAYER] page {page_num+1}: SHREDDED TEXT LAYER — "
                        f"{stats['shard_ratio']:.2f}x more words read without "
                        f"font size than with it. Several texts are set at "
                        f"different sizes over the same lines and their "
                        f"characters interleave; they have been separated and "
                        f"this page's text rebuilt. CHECK THIS PAGE BY HAND. "
                        f"(This check does NOT detect scanned pages or thin "
                        f"OCR text layers.)",
                        flush=True
                    )
                # OVERPRINT DETECTION: performed, or recorded as not performed.
                # Never silently absent — an absent per-word flag already means
                # "this word is clean", so a reader that cannot look would
                # otherwise report a clean document.
                if stats.get("overprint_checked", True) is False:
                    doc.unchecked_overprint_pages.append(page_num + 1)
                if repairs:
                    doc.text_repairs.extend(repairs)
                    print(
                        f"[TEXTLAYER] page {page_num+1}: reassembled "
                        f"{len(repairs)} value(s) the PDF wrapped inside a "
                        f"cell: " + ", ".join(f"{a!r}+{b!r}->{f!r}"
                                              for a, b, f in repairs[:6]),
                        flush=True
                    )
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

    # Determine if text extraction was meaningful — FROM THE DOCUMENT'S OWN
    # TEXT LAYER. A scan whose text came from OCR stays `scanned_pdf`, so
    # slot extraction still floors its confidences to UNVERIFIED: OCR gives
    # the model something to read and grounding something to check against, and
    # it does not make a machine's reading into the document's own words.
    clean_text = doc.extracted_text.strip()
    native = doc.native_text_chars if doc.ocr_pages else len(clean_text)
    doc.has_meaningful_text = native > MIN_TEXT_LENGTH

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
