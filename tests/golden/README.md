# Owner-run truth files

Each JSON file is a hand-verified, document-first truth record. Values came from the PDF text layer, AcroForm widgets, or direct image inspection; they were not copied from DocAgent output.

Required keys:

- `file`, `template_name`, and `document_type` identify the run.
- `headers` and `totals` map labels to typed expected values.
- `tables` records the exact row count plus a small set of identity-bearing key rows.
- `absent_slots` distinguishes a fact that is not printed from a fact the extractor missed.

Money is stored as JSON numbers. Identifiers, ZIP codes, masked tax IDs, and last-four values are strings. A numeric zero is a real value. It must never be treated as an empty slot.

The 14 owner runs are supplemented by seven verifiable files from the workbook's `Answers` sheet. The workbook is only a cross-check; the source document remains authoritative.

Verified correction: `flowparse_cafe.pdf` prints `FERN & COPPER CAFÉ`, with an accented final letter. The truth file preserves that spelling instead of the unaccented wording in the task brief.
