# Proposal: OCR language packs

**Status:** proposal (Part 1.4). Not done: it changes the production image.

Tesseract reads a script only with its trained data. The image installs
`tesseract-ocr` with `eng` and `osd`, so a scanned Hindi, Arabic or Japanese
page is read as Latin noise; the text-layer path is unaffected (it reads
whatever the PDF holds) and every such value is flagged `non_english_text`.

| Script / language | Debian package | Approx. size |
|---|---|---|
| Hindi (Devanagari) | `tesseract-ocr-hin` | ~1 MB (fast) / ~10 MB (best) |
| Arabic | `tesseract-ocr-ara` | ~1–3 MB |
| Japanese / Chinese | `tesseract-ocr-jpn`, `-chi-sim`, `-chi-tra` | 2–15 MB each |
| Bengali, Tamil, Telugu, Gujarati, … | `tesseract-ocr-ben`, `-tam`, `-tel`, `-guj` | ~1–5 MB each |
| French, German, Spanish | `tesseract-ocr-fra`, `-deu`, `-spa` | ~1–3 MB each |

What adopting it needs:

1. Install the packs a client actually needs in `Dockerfile.backend`, never
   all of them (image size, cold start).
2. A per-firm or per-template `ocr_languages` (`eng+hin`), passed as `lang=`
   to `pytesseract` in `engine/ocr_source.py`; `reader_identity` records it.
3. Measurement on the client's own scans before any value from them is read
   as more than `unverified` (the OCR-READER-SEAM-DESIGN.md rule).
4. The checks stay English: `non_english_text` remains on every such value
   until prompts, labels and number words exist for that language.
