# Throughput of the OCR path — measurement and proposal

**Status:** measured, not implemented. Measured 2026-10-23 on the development
machine (8 logical CPUs, Windows 11, Tesseract and Poppler on PATH), on
synthetic cheque pages (`tests/test_OCR/chk_*_clean.png` and `_moderate.jpg`,
cycled into PDFs of 1, 10 and 50 pages). No model call is included: this is
`preprocess_file` — render, orientation, deskew, OCR, line building. The
script is reproducible; it times the engine's own functions by wrapping them.

## Numbers

| pages | seconds | per page |
|---|---|---|
| 1 | 5.7 | 5.7 |
| 10 | 47.7 | 4.8 |
| 50 | 236.2 | 4.7 |

Where a page's 4.7 s goes (50-page run, per page):

| stage | seconds | share |
|---|---|---|
| orientation (Tesseract OSD, `ocr_source.orientation`) | 1.79 | 38% |
| OCR (`pytesseract.image_to_data`, inside `read_page`) | 1.45 | 31% |
| render (`pdf2image` → `pdftoppm`, one process per page at 300 dpi) | 1.13 | 24% |
| skew detection (`skew_angle`) | 0.23 | 5% |
| straighten / rotate, line building, text-layer probing | ~0.1 | 2% |

Grounding against the OCR lines is not in this table: it runs per value
after the model answers and costs milliseconds per document.

Per-page OCR in a process pool (`_ocr_page` per page, same 50 pages):

| workers | seconds | per page | speed-up |
|---|---|---|---|
| 1 (serial) | 236 | 4.7 | 1.0× |
| 2 | 125 | 2.5 | 1.9× |
| 4 | 74 | 1.5 | 3.2× |

Every page read the same number of words in the pool as serially (50 of 50
pages with words): the stages are per page and share no state.

## What it means for the first customer

50 cheques a day is about 4 minutes of OCR serially, plus one model call per
cheque. That is acceptable for a batch an accountant starts and comes back
to; it is not acceptable for one-at-a-time interactive use, and it scales
linearly with no parallelism today.

## Recommendation, in order

1. **OCR pages in a process pool** (largest, safest win: ~3× at 4 workers).
   `_process_pdf` would render and OCR the pages needing OCR in a
   `ProcessPoolExecutor`, then fold results back IN PAGE ORDER into the
   `ProcessedDocument` (texts, lines, `ocr_pages`, `ocr_images`, failure
   lists). Deterministic by construction if results are keyed by page number
   and merged in order. Not done in this round because it changes the
   preprocessor's page loop, which holds several gates (selective OCR,
   pre-OCR detection, failure lists) whose order is part of the result; it
   needs its own review. Cap workers at `min(4, cpu_count - 1)` on Railway,
   where the container's CPU share is the real limit — measure there first.
2. **Render once per file**, not once per page: `convert_from_path` on the
   whole range in one `pdftoppm` call removes most of the 24% render cost
   for multi-page files (the process start dominates at one page per call).
3. **Skip OSD when the page is upright with confidence.** Orientation is
   38%; a cheap pre-check (the first OCR pass reads enough dictionary words,
   or the MICR band is found in the bottom strip) could skip OSD on most
   pages. This changes which pages are rotated in edge cases, so it needs
   the OCR harness (`tests/harness/ocr_checks.py`) before and after.
4. Keep 300 dpi: the OCR accuracy work in DECISION-LOG / the seam design was
   measured at it; lowering it trades accuracy for speed without measurement.
