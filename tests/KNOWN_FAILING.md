# Strict acceptance xfails

Every item below is `xfail(strict=True)`. These are real application gaps, not
adapter/name mismatches. A future implementation that makes one pass will fail
as XPASS until its marker and this row are removed.

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| (none open in this file) | | | |

Run C removed the three A6 rows (compact reserved bands, exactly three blank
rows between documents, clean default columns): `excel_slot._write_slot_excel`
writes each band with its actual row count, `GAP_BETWEEN_DOCS = 3`, and the
Source / Review status columns are opt-in (`include_audit`). The markers came
off in the same commit as the fix.

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

## Template layout audit

All entries below are exercised by `tests/test_template_layout_audit.py`; every
listed failure is `xfail(strict=True)`. The paired workbook and independent
truth file live under `tests/templates/`.

| Scenario | Strict test(s) | Observed application gap |
| --- | --- | --- |
| F2 | parse, write | `Invoice Date \| _ \| Approval Code` has F4's same-row-pair geometry; F2's truth wants the cells below and F4's the cells right. Run D's D9 takes the cell below only when the right one is not usable, and here it is. |
| F3 | parse, write | Empty separator columns do not survive the text-defined used range. |
| F9 | write | Number formats and dropdown validation are outside the saved grid. |
| F10 | parse, write | Formula strings participate in label geometry. |
| F12 | write | Hidden row and column state is not preserved. |
| T2 | parse | 0 reserved rows wanted under a header-only band; `tests/test_prod_templates.py` pins the same shape (production `bank_statement_101`) at >= 5. Contradictory tests: owner's decision. |
| T13 | parse | As T2. |
| T6 | parse | Both bands are detected and written (Run D); the truth's band names `left`/`right` are printed nowhere, and its closing `End left`/`End right` labels expect no slot while T1's `Total` in the same position expects one. |
| T9 | write | Parse passes (Run D). The truth expects the text `Item` in A2 and also keeps the A1:A2 merge that covers it. |
| T10 | parse, write | Needs non-geometric readings: a blank row before a total is a spacer (not capacity), `Total above` over a header is a total (the gold payslip's `Earnings` in that position is a title), and closing `End` rows get no slot. |
| T11 | write | The subtotal keeps its place and records go around it (Run D). The test expects records in rows 2-6 contiguously and the subtotal formula in E4 at the same time. |
| T12 | parse, write | Transposed tables require an editor declaration. |
| T14 | parse, write | Excel Table metadata is ignored and not recreated. |
| T15 | parse | Fields beside the band are read and written (Run D); the truth gives the closing `End \| _` row no slot while T1's `Total \| _` in the same position has one. |
| T18 | parse, write | Only the first workbook sheet enters the grid and output. |
| T21 | write | Blocks are compact (Run C/D); the test expects 2 blank rows between documents, Run C's acceptance test exactly 3. |

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
