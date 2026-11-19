# Strict acceptance xfails

Every item below is `xfail(strict=True)`. These are real application gaps, not
adapter/name mismatches. A future implementation that makes one pass will fail
as XPASS until its marker and this row are removed.

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| A6 compact reserved table bands | `test_unused_reserved_rows_are_removed_and_totals_touch_the_band` | `backend/app/services/excel_slot.py:167-170` shifts only when rows overflow the reserved band; it has no contraction path. | Subtotal stays on row 11 after two extracted rows; it should touch the band on row 9. |
| A6 exactly three blank rows between documents | `test_multiple_documents_have_header_strip_and_exactly_three_blank_rows` | `backend/app/services/excel_slot.py:233,537-538` hard-codes `GAP_BETWEEN_DOCS = 2`. | The export has two blank rows, not three. |
| A6 clean default export columns | `test_default_download_hides_source_and_review_columns_but_opt_in_restores_them` | `backend/app/api/routes/extract.py:626-647` defaults `provenance=True`; `backend/app/services/excel_slot.py:162-179` defaults review marks/status on. | Default output exposes `Source` and `Review status` columns. |

Run B removed the A8.3 row (row sum versus printed total): `source_inventory.row_sum_checks`
now produces a `row_sum_mismatch` reason and the strict marker came off in the same commit.

## Reclassified naming problems

- The guessed `app.services.completeness_gate` entry points did not exist.
  Tests now use `llm_contract`, `source_inventory`,
  `slot_extractor.run_slot_extraction`, and the real review/edit HTTP routes.
- Completeness reasons are `attention[]` items with plain `text` and a nested
  `disposition`, while deterministic coverage detail is under
  `diagnostics.coverage`; the old tests guessed `diagnostics.reasons`.
- The page ledger is `diagnostics.pages` with `processed`, `processed_empty`,
  and `failed`, not a synthetic `coverage.page_ledger` object.
- W-2 mod11's filled widget is `10535`, and that exact text reaches the model
  input. The old `10,535` needle was wrong.

Baseline before alignment: **74 collected, 28 passed, 42 xfailed, 4 failed**
(the four failures were the local Poppler setup). Aligned suite target:
**80 collected, 76 passed, 4 xfailed**. The acceptance test tooling uses the
installed local PDFium/Tesseract seams, so the result does not depend on a
Poppler executable being present on the developer machine.
