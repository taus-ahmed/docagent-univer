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
    #: Pages OCR ran on and read ZERO words from. A blank scan is not a
    #: successful reading: nothing says the page is empty rather than
    #: unreadable, so it is a named failure, kept apart from
    #: `ocr_failed_pages` (OCR could not run at all). Such a page still has
    #: its record in `ocr_pages`, words=0, because OCR did run.
    ocr_zero_word_pages: list[int] = field(default_factory=list)
    #: Characters the PDF's OWN text layer yielded on its NATIVE pages — not
    #: OCR's reading, and not a scanner's embedded layer. Kept apart
    #: from `extracted_text` because `has_meaningful_text` decides the document
    #: type, and a document typed `digital_pdf` on the strength of text a
    #: machine read off a picture would claim `high` confidence for values no
    #: text layer ever witnessed.
    native_text_chars: int = 0
    #: Where each page's text came from, one entry per page in file order:
    #:   "native"   the PDF's own text layer — the document's own words
    #:   "ocr"      no usable text layer; read (or attempted) by OCR here
    #:   "pre_ocr"  a text layer that is itself a machine's reading: text drawn
    #:              INVISIBLY (render mode 3) over a page image, which is what
    #:              a scanner or MFP that ran its own OCR writes
    #: Decided per page, so one scan in a file says nothing about its other
    #: pages. Only strong, explainable signals decide (`page_origin`); image
    #: coverage on its own never does — the CFPB forms carry an 86% image on
    #: page 1 and are native. Gate 2c adds one: a page one image covers whose
    #: visible text layer holds under half the words OCR reads is "ocr"
    #: (`_selective_ocr`); the cover only decides which pages are compared.
    page_origins: list[str] = field(default_factory=list)
    #: {file page: (straightened PIL image, dpi)} for every page OCR read —
    #: the image the reader SAW, in the frame its word boxes are in. Kept so
    #: a page holding several cheques can be cut into regions whose crops
    #: match their words (engine/cheque_regions.py). Never serialised.
    ocr_images: dict = field(default_factory=dict)
    #: Gate 2c — pages that qualified for selective OCR (an image covering the
    #: page, a native text layer) where OCR then failed or read nothing, so
    #: the page had to stay native with no way to know how much of it the text
    #: layer carries: [{page, image_cover, native_words, ocr_words, ocr}],
    #: `ocr` = "failed" | "zero_words". Reported as `thin_text_layer`.
    thin_text_pages: list[dict] = field(default_factory=list)
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

#: GATE 2c — SELECTIVE OCR. A page whose text layer is VISIBLE (so neither
#: `page_needs_ocr` nor the invisible-text test fires) but that is a picture of
#: the page with a few words laid over it. Measured on every image-bearing page
#: in tests/test_pdfs (2026-10-23): bank-statement-sample is one image covering
#: 1.00 of the page and its layer holds 108 words against OCR's 485 (0.22); the
#: CFPB forms' largest image covers 0.86, everything else <= 0.05, and every
#: native/OCR word ratio there is >= 0.94. BOTH conditions are required: the
#: cover decides which pages pay for an OCR pass (1 of 114 corpus pages), the
#: ratio decides the reading. An image alone never decides — a full-page form
#: background under a complete text layer reads ~1.0 and stays native.
SELECTIVE_OCR_COVER = 0.99
SELECTIVE_OCR_RATIO = 0.5

#: What joins page texts into `extracted_text`. `_fix_cross_page_decimals`
#: looks for exactly this, so anything re-joining a subset of pages uses it.
PAGE_BREAK = "\n\n--- PAGE BREAK ---\n\n"


def page_needs_ocr(text: str) -> bool:
    """Would this page's text layer send it to OCR? THE one rule.

    It was written inline in `_process_pdf` and nowhere else, so a caller that
    needed to ask the question BEFORE reading a document — the demo upload gate
    is the first — had no way to ask it without restating the threshold. A
    second statement of a threshold is a second threshold: the two drift and
    nothing fails when they do. This is that rule, named, with both callers
    going through it.
    """
    return len((text or "").strip()) < MIN_TEXT_LENGTH


def text_layer_pages(file_path: str | Path) -> tuple[list[int], int]:
    """(the 1-based pages `_process_pdf` would send to OCR, the page count).

    Reads the PDF's own text layer and NOTHING else: it renders no page, runs
    no OCR, and calls no model. It reads each page exactly the way the pipeline
    does (`read_page`, with the file's AcroForm markers) so that the answer is
    the pipeline's answer and not an approximation of it.

    BOTH NUMBERS COME FROM ONE PARSE, because the interesting questions are
    ratios — "is any page a scan" and "is EVERY page a scan" are different
    questions with different answers, and a caller that has to open the file a
    second time to learn the denominator will sooner or later compare two
    readings of two different files.

    Raises whatever pdfplumber raises on a file that is not a readable PDF —
    the caller is deciding whether to accept an upload and must not read "this
    file is corrupt" as "this file is fine".
    """
    path = Path(file_path)
    widgets = acroform_widgets(path) or {}
    missing: list[int] = []
    total = 0
    with pdfplumber.open(path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            total += 1
            text, _lines, _repairs = read_page(
                page, widgets.get(page_num) or [], stats={})
            if page_needs_ocr(text):
                missing.append(page_num + 1)
    return missing, total


def pages_without_text_layer(file_path: str | Path) -> list[int]:
    """The 1-based pages of this PDF that `_process_pdf` would send to OCR."""
    return text_layer_pages(file_path)[0]


#: Text show operators, and the operator that changes the text render mode.
_SHOW_OPS = {b"Tj", b"TJ", b"'", b'"'}
#: Render mode 3 paints nothing: neither fill nor stroke, nor a clip.
_INVISIBLE = 3


def invisible_text_shows(page) -> tuple[int, int]:
    """(text shows drawn in render mode 3, all text shows) on one pypdf page.

    Walks the page's content stream AND every form XObject it draws, tracking
    `Tr` through `q`/`Q` the way a renderer does — the render mode is part of
    the graphics state, so it survives `BT`/`ET` and is restored by `Q`, and a
    form starts from the state current at its `Do` and gives it back after.

    pdfplumber's characters do not carry the render mode, which is why this
    reads the stream itself.
    """
    from pypdf.generic import ContentStream

    counts = [0, 0]

    def walk(contents, resources, mode, depth):
        if contents is None or depth > 8:
            return
        stack = []
        for operands, op in ContentStream(contents, page.pdf).operations:
            if op == b"q":
                stack.append(mode)
            elif op == b"Q":
                mode = stack.pop() if stack else mode
            elif op == b"Tr" and operands:
                mode = int(operands[0])
            elif op in _SHOW_OPS:
                counts[1] += 1
                counts[0] += mode == _INVISIBLE
            elif op == b"Do" and operands and resources is not None:
                xobjects = resources.get("/XObject")
                xobj = xobjects.get_object().get(operands[0]) if xobjects else None
                xobj = xobj.get_object() if xobj is not None else None
                if xobj is not None and xobj.get("/Subtype") == "/Form":
                    walk(xobj, xobj.get("/Resources", resources), mode, depth + 1)

    walk(page.get_contents(), page.get("/Resources"), 0, 0)
    return counts[0], counts[1]


def page_origin(plumber_page, pypdf_page, needed_ocr: bool) -> str:
    """"native" | "ocr" | "pre_ocr" for one page. See `ProcessedDocument`.

    THE SIGNALS, strongest first, and why each one is allowed to decide:

      no usable text layer      the page went to OCR: "ocr", whatever OCR
                                then managed (a failure or zero words is a
                                named outcome of its own, not a native page)
      invisible text over an    "pre_ocr". Text that is never painted exists
      image                     only to be searched; drawn over a picture of
                                the page it is a scanner's reading of that
                                picture. Most of the page's text shows must be
                                invisible, so one hidden marker on a digital
                                form does not condemn it.
      otherwise                 "native"

    An image is required as CORROBORATION and is never sufficient: an image
    without hidden text is a digital page with a logo, a seal or a form
    background (the three CFPB controls: 86% image cover, 0 hidden shows).
    A page whose text layer is VISIBLE but thin over a full-page image — the
    Photoshop-built bank-statement-sample — is not decided here; telling it
    apart needs an OCR-versus-text-layer comparison (Gate 2c).
    """
    if needed_ocr:
        return "ocr"
    if pypdf_page is None or not plumber_page.images:
        return "native"
    hidden, shows = invisible_text_shows(pypdf_page)
    return "pre_ocr" if shows and hidden * 2 > shows else "native"


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
              stats: dict, image=None, dpi=None):
    """(text, lines, repairs) for a page with no text layer, read by OCR.

    THROUGH THE SEAM, NOT AROUND IT. `read_page` takes a `PageSource`, so the
    OCR reader is handed to the same function the pdfplumber reader goes
    through: wrapped-value repair, page stamping and the capability gates all
    run exactly as they do for a digital page, and the gates SKIP loudly
    because `OcrPageSource` declares nothing.

    A failure here is recorded, never swallowed: a page that could not be OCR'd
    is listed in `ocr_failed_pages` and comes back as empty as it was before,
    which is the honest answer — but a named one.

    `image` (with its own `dpi`) is a page that is ALREADY a picture — an
    uploaded JPG/PNG — and is read exactly as a rendered page is.
    """
    try:
        from ocr_source import OcrPageSource, OCR_DPI, render_pdf_page
        dpi = dpi or OCR_DPI
        if image is None:
            image = render_pdf_page(file_path, page_number, dpi=dpi)
        if image is None:
            raise RuntimeError("the page could not be rendered")
        source = OcrPageSource(image, page_number=page_number, dpi=dpi)
        text, lines, repairs = read_page(source, stats=stats)
    except Exception as exc:
        doc.ocr_failed_pages.append(page_number)
        doc.processing_notes += (
            f"page {page_number} has no text layer and could not be OCR'd "
            f"({type(exc).__name__}: {exc}). ")
        print(f"[OCR] page {page_number}: NO TEXT LAYER and OCR unavailable — "
              f"{type(exc).__name__}: {exc}", flush=True)
        return "", [], []

    from ocr_source import reader_identity
    words = sum(len(ln) for ln in lines)
    straightened = getattr(source, "_image", None)
    if straightened is not None:
        doc.ocr_images[page_number] = (straightened, dpi)
    doc.ocr_pages.append({"page": page_number, "words": words, **source.applied,
                          "dpi": dpi, **reader_identity()})
    if not words:
        doc.ocr_zero_word_pages.append(page_number)
        doc.processing_notes += (
            f"page {page_number} has no text layer and OCR read zero words "
            f"from it — blank or unreadable; nothing was extracted from this "
            f"page. ")
    print(f"[OCR] page {page_number}: no text layer — read by Tesseract at "
          f"{dpi}dpi, rotated {source.applied['rotated']}deg, deskewed "
          f"{source.applied['deskewed']}deg ({source.applied.get('skew_detector', 'none')}), "
          f"retry {source.applied.get('retry', 'none')}, {len(text)} chars, "
          f"{sum(len(ln) for ln in lines)} words. These are a MACHINE's "
          f"reading, not the document's own text.", flush=True)
    return text, lines, repairs


def largest_image_cover(page) -> float:
    """The largest single image's share of the page area, clipped to the page."""
    area = float(page.width * page.height) or 1.0
    best = 0.0
    for im in page.images or []:
        w = max(0.0, min(float(im["x1"]), float(page.width)) - max(float(im["x0"]), 0.0))
        h = max(0.0, min(float(im["bottom"]), float(page.height))
                - max(float(im["top"]), 0.0))
        best = max(best, w * h / area)
    return best


def _selective_ocr(file_path: Path, page_number: int, doc: "ProcessedDocument",
                   lines, cover: float):
    """Gate 2c for one native page whose largest image covers it: OCR it, and
    return (text, lines, repairs, stats) when the text layer holds under
    SELECTIVE_OCR_RATIO of OCR's words — the page is then read through the
    OCR seam — else None, the page staying native.

    OCR runs into a scratch record, so a page that stays native is never
    reported as one with "no text layer" (`ocr_failed_pages`) or as a blank
    scan; only the outcome is copied across. A failed or empty OCR is not a
    pass: the page is listed in `thin_text_pages`, whose reason is
    `thin_text_layer`.
    """
    scratch = ProcessedDocument(source_path=str(file_path), filename=doc.filename,
                                file_type="pdf", total_pages=doc.total_pages)
    stats: dict = {}
    text, olines, repairs = _ocr_page(file_path, page_number, scratch, stats)
    native = sum(len(ln) for ln in lines or [])
    words = sum(len(ln) for ln in olines or [])
    measured = {"image_cover": round(cover, 3), "native_words": native,
                "ocr_words": words}
    if scratch.ocr_failed_pages or not words:
        doc.thin_text_pages.append({
            "page": page_number, **measured,
            "ocr": "failed" if scratch.ocr_failed_pages else "zero_words"})
        doc.processing_notes += (
            f"page {page_number}: an image covers the page and its text layer "
            f"could not be compared with an OCR reading (OCR "
            f"{'failed' if scratch.ocr_failed_pages else 'read zero words'}); "
            f"the text layer may carry only part of what the page shows. ")
        print(f"[OCR] page {page_number}: THIN TEXT LAYER UNCHECKED — image "
              f"cover {cover:.2f}, {native} native word(s), OCR unavailable",
              flush=True)
        return None
    ratio = round(native / words, 3)
    if ratio >= SELECTIVE_OCR_RATIO:
        return None
    entry = dict(scratch.ocr_pages[-1])
    entry["selective_ocr"] = {**measured, "ratio": ratio,
                              "cover_threshold": SELECTIVE_OCR_COVER,
                              "ratio_threshold": SELECTIVE_OCR_RATIO}
    doc.ocr_pages.append(entry)
    doc.ocr_images.update(scratch.ocr_images)
    print(f"[OCR] page {page_number}: SELECTIVE OCR — image cover {cover:.2f}, "
          f"text layer {native} word(s) against OCR's {words} ({ratio}); read "
          f"through the OCR seam, origin ocr", flush=True)
    return text, olines, repairs, stats


def _process_pdf(file_path: Path) -> ProcessedDocument:
    """Process a PDF file: extract text from ALL pages and convert to images."""
    doc = ProcessedDocument(
        source_path=str(file_path),
        filename=file_path.name,
        file_type="pdf",
    )

    # Step 1: Extract text from ALL pages using pdfplumber
    reader = None
    try:
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
                needed_ocr = page_needs_ocr(text)
                # The pypdf reader is opened only for a page that could be a
                # pre-OCR'd scan (a usable text layer AND an image), so a plain
                # digital document pays nothing for the question.
                if reader is None and not needed_ocr and page.images:
                    reader = PdfReader(str(file_path))
                try:
                    origin = page_origin(
                        page, reader.pages[page_num] if reader else None,
                        needed_ocr)
                except Exception as exc:
                    # Said out loud. A page whose stream cannot be walked is
                    # left native — calling it a scan on no evidence would put
                    # a digital form under the OCR floor.
                    origin = "native"
                    doc.processing_notes += (
                        f"page {page_num + 1}: could not check for an embedded "
                        f"OCR layer ({type(exc).__name__}: {exc}). ")
                # GATE 2c. Only a native page with an image covering it pays
                # for the OCR pass; every other page is untouched.
                if origin == "native" and page.images:
                    cover = largest_image_cover(page)
                    if cover >= SELECTIVE_OCR_COVER:
                        read = _selective_ocr(file_path, page_num + 1, doc,
                                              lines, cover)
                        if read is not None:
                            text, lines, repairs, ocr_stats = read
                            stats.clear()
                            stats.update(ocr_stats)
                            origin = "ocr"
                doc.page_origins.append(origin)
                if origin == "native":
                    doc.native_text_chars += len((text or "").strip())
                elif origin == "pre_ocr":
                    print(f"[TEXTLAYER] page {page_num+1}: EMBEDDED OCR LAYER "
                          f"— its text is drawn invisibly over a page image, "
                          f"so it is a machine's reading of that image, not "
                          f"the document's own words.", flush=True)
                # A PAGE WITH NO TEXT LAYER IS NOT A PAGE WITH NOTHING ON IT.
                # pdfplumber returns nothing for a scan, and everything
                # downstream — the prompt, grounding, placement, row identity —
                # then has nothing to work with and says so only by being
                # empty. Render it and read it with OCR instead, through the
                # SAME seam: `read_page` takes a PageSource, so nothing below
                # this line learns that a different reader ran.
                if needed_ocr:
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
            doc.extracted_text = PAGE_BREAK.join(doc.page_texts)

            # Fix cross-page decimal splits AFTER joining all pages
            doc.extracted_text = _fix_cross_page_decimals(doc.extracted_text)

    except Exception as e:
        doc.processing_notes += f"Text extraction failed: {e}. "

    # Determine if text extraction was meaningful — FROM THE DOCUMENT'S OWN
    # TEXT LAYER, counted over NATIVE pages only. Text that OCR read here, or
    # that a scanner embedded (pre_ocr), gives the model something to read and
    # grounding something to check against; it does not make a machine's
    # reading into the document's own words. Per-value confidence is decided
    # by each value's PAGE origin (`page_origins`), so a mixed file is no
    # longer a scan because one of its pages is.
    doc.has_meaningful_text = doc.native_text_chars > MIN_TEXT_LENGTH

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
        page = img if img.mode in ("RGB", "L") else img.convert("RGB")
        dpi = _image_dpi(img)
        doc.page_images_b64.append(_image_to_base64(_optimize_image(img)))
    except Exception as e:
        doc.processing_notes += f"Image processing failed: {e}. "
        raise

    # AN IMAGE IS A SCANNED PAGE. It used to reach the engine as a picture
    # alone — no text, no geometry, no origin — so nothing could be grounded
    # and every value was floored to `unverified` without one check having
    # run. It is now read through the SAME seam a scanned PDF page is, at
    # full resolution (the model's copy above is downscaled; the reader's is
    # not): origin "ocr", OCR metadata, the per-page floor and every check.
    # Only the first frame of a multi-frame TIFF is read, as before.
    stats = {}
    text, lines, repairs = _ocr_page(file_path, 1, doc, stats, image=page,
                                     dpi=dpi)
    doc.page_origins.append("ocr")
    doc.page_lines.append(lines)
    if stats.get("shard_checked", True) is False:
        doc.unchecked_shred_pages.append(1)
    if stats.get("overprint_checked", True) is False:
        doc.unchecked_overprint_pages.append(1)
    if repairs:
        doc.text_repairs.extend(repairs)
    text = _fix_within_page_decimals(text)
    doc.page_texts.append(text)
    doc.extracted_text = text
    return doc


def _image_dpi(img) -> float:
    """The resolution the image says it was scanned at, or the OCR default.

    A file's own dpi is trusted only inside a plausible scanning range; many
    encoders write 72 (a screen default, not a measurement) or nothing.
    """
    from ocr_source import OCR_DPI
    try:
        d = float((img.info.get("dpi") or (0, 0))[0])
    except (TypeError, ValueError, IndexError):
        d = 0.0
    return d if 100.0 <= d <= 1200.0 else float(OCR_DPI)


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
