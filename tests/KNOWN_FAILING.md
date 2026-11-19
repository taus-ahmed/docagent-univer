# Strict acceptance xfails

Every item below is `xfail(strict=True)`. These are real application gaps, not
adapter/name mismatches. A future implementation that makes one pass will fail
as XPASS until its marker and this row are removed.

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| A6 compact reserved table bands | `test_unused_reserved_rows_are_removed_and_totals_touch_the_band` | `backend/app/services/excel_slot.py:167-170` shifts only when rows overflow the reserved band; it has no contraction path. | Subtotal stays on row 11 after two extracted rows; it should touch the band on row 9. |
| A6 exactly three blank rows between documents | `test_multiple_documents_have_header_strip_and_exactly_three_blank_rows` | `backend/app/services/excel_slot.py:233,537-538` hard-codes `GAP_BETWEEN_DOCS = 2`. | The export has two blank rows, not three. |
| A6 clean default export columns | `test_default_download_hides_source_and_review_columns_but_opt_in_restores_them` | `backend/app/api/routes/extract.py:626-647` defaults `provenance=True`; `backend/app/services/excel_slot.py:162-179` defaults review marks/status on. | Default output exposes `Source` and `Review status` columns. |

## Run B independent adversarial review

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| B3 two-account last-four ambiguity | `test_last_four_flags_even_when_model_picks_one_of_two_accounts` | `backend/engine/format_rules.py:69-71` returns `ok` as soon as the supplied four digits match any candidate, before checking how many accounts/cards the page contains. | `Account 11110088` plus `Card 22220011` accepts `0088`; the page is ambiguous and should be flagged. |
| B3 routing number mistaken for an account | `test_routing_number_is_not_a_last_four_candidate` | `backend/engine/format_rules.py:25` makes the generic word `Number` a cue, and `account_numbers` does not exclude `Routing Number`. | With routing `071000505` and account `7301558842`, the bad model value `58842` is left ambiguous instead of uniquely corrected to `8842`. |
| B4 legitimate diagonal stamp removal | `test_small_diagonal_paid_stamp_is_not_a_watermark` | `backend/engine/text_layer.py:1277-1282` removes every glyph rotated 10-80 degrees regardless of font size or repeated/background evidence. | A body-size, 35-degree `PAID` stamp is classified as watermark text and removed. |
| B6 signed Less line false mismatch | `test_row_sum_respects_less_lines_and_parenthesized_negatives` | `backend/engine/source_inventory.py:68` applies `abs()` to every parsed amount before `row_sum_checks` sums it. | `100.00 + (20.00) = 80.00` is computed as `120.00` and the correct printed total is flagged. |
| B6 multi-page subtotal false mismatch | `test_row_sum_accepts_per_page_subtotals_in_a_multi_page_band` | `backend/engine/source_inventory.py:639-679` flattens every page and ignores row `_page`/`page_numbers` while comparing one all-pages row sum to each printed subtotal. | Two pages that each sum correctly to `100.00` are treated as a `200.00` band and flagged. |

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
