# Strict acceptance xfails

Every item in the first table is `xfail(strict=True)`. These are real
application gaps, not adapter/name mismatches. A future implementation that
makes one pass will fail as XPASS until its marker and this row are removed.

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |

## Harness regression (resolved by Run E, E0)

`test_harness_reader_does_not_hide_a_duplicate_total_row` passes: the reader
now ends a band at the LAST place inside the reserved area where the
template's own rows line up, so a duplicate `Total` band row is reported as a
table row. Extraction cannot write that duplicate (`split_duplicate_totals`
drops it, `tests/test_run_e_fixes.py`); only a human edit or a pre-Run C job
can, so the writer is unchanged.

Run C removed the three A6 rows (compact reserved bands, exactly three blank
rows between documents, clean default columns): `excel_slot._write_slot_excel`
writes each band with its actual row count, `GAP_BETWEEN_DOCS = 3`, and the
Source / Review status columns are opt-in (`include_audit`). The markers came
off in the same commit as the fix.

## Run B independent adversarial review (resolved by Run D)

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| B3 two-account last-four ambiguity | `test_last_four_flags_even_when_model_picks_one_of_two_accounts` | `backend/engine/format_rules.py:69-71` returns `ok` as soon as the supplied four digits match any candidate, before checking how many accounts/cards the page contains. | `Account 11110088` plus `Card 22220011` accepts `0088`; the page is ambiguous and should be flagged. |
| B3 routing number mistaken for an account | `test_routing_number_is_not_a_last_four_candidate` | `backend/engine/format_rules.py:25` makes the generic word `Number` a cue, and `account_numbers` does not exclude `Routing Number`. | With routing `071000505` and account `7301558842`, the bad model value `58842` is left ambiguous instead of uniquely corrected to `8842`. |
| B4 legitimate diagonal stamp removal | `test_small_diagonal_paid_stamp_is_not_a_watermark` | `backend/engine/text_layer.py:1277-1282` removes every glyph rotated 10-80 degrees regardless of font size or repeated/background evidence. | A body-size, 35-degree `PAID` stamp is classified as watermark text and removed. |
| B6 signed Less line false mismatch | `test_row_sum_respects_less_lines_and_parenthesized_negatives` | `backend/engine/source_inventory.py:68` applies `abs()` to every parsed amount before `row_sum_checks` sums it. | `100.00 + (20.00) = 80.00` is computed as `120.00` and the correct printed total is flagged. |
| B6 multi-page subtotal false mismatch | `test_row_sum_accepts_per_page_subtotals_in_a_multi_page_band` | `backend/engine/source_inventory.py:639-679` flattens every page and ignores row `_page`/`page_numbers` while comparing one all-pages row sum to each printed subtotal. | Two pages that each sum correctly to `100.00` are treated as a `200.00` band and flagged. |

Run B removed the A8.3 row (row sum versus printed total): `source_inventory.row_sum_checks`
now produces a `row_sum_mismatch` reason and the strict marker came off in the same commit.

## Part 1 owner rulings

1. **T2/T13:** header-only bands keep the production minimum (currently ten
   synthetic rows, satisfying the `>= 5` production test). The audit truth now
   expects ten; unused rows are dropped on export, so output is unchanged.
2. **T21:** document blocks use exactly three blank rows, matching the owner
   spec, `GAP_BETWEEN_DOCS = 3`, and Run C acceptance.
3. **F2:** a usable cell to the right wins, exactly as F4. True vertical intent
   remains a strict future-need xfail because the editor needs an explicit
   **value below** setting.
4. **T6/T10/T15:** every labelled cell with an empty neighbour is a slot,
   including `End | _`. Semantic names, spacer-versus-capacity, and whether an
   `End` row belongs inside a table need editor declarations (`Table ↓` /
   `Table →`) and are isolated in strict xfails whose reason is
   `needs declared tables`.
5. **T9/T11:** write truth now respects physical Excel constraints: `Item`
   stays at the A1 anchor of merge A1:A2, and T11 records skip E4 while its
   subtotal formula remains there.
6. **Watermark audit:** its corpus is only `tests/fixtures/acceptance`; an
   owner's untracked `local_docs` can no longer change the count.
7. **Recorded bank golden:** `Bank_Recon` has no full-account-number slot, so
   `Account Number` is in `absent_slots`; only the last-four value is expected.

## Template layout audit

All entries below are exercised by `tests/test_template_layout_audit.py`; every
listed failure is `xfail(strict=True)`. The paired workbook and independent
truth file live under `tests/templates/`.

| Scenario | Strict test(s) | Observed application gap |
| --- | --- | --- |
| F2 | future editor intent | Horizontal B1/D1 is the correct current geometry. True label-above/value-below needs an explicit editor setting. |
| F3 | parse, write | Empty separator columns do not survive the text-defined used range. |
| F9 | write | Number formats and dropdown validation are outside the saved grid. |
| F10 | parse, write | Formula strings participate in label geometry. |
| F12 | write | Hidden row and column state is not preserved. |
| T6 | declared intent | Inferred `table_1`/`table_2` and the two `End | _` slots are correct; semantic names and claimed closing rows need declared tables. |
| T10 | declared intent | Inferred geometry treats the blank as capacity, `Total above` as a title, and `End | _` as slots. Different intent needs declared tables. |
| T12 | parse, write | Transposed tables require an editor declaration. |
| T14 | parse, write | Excel Table metadata is ignored and not recreated. |
| T15 | declared intent | `Owner`, `Reviewed`, and `End | _` are valid inferred slots. Claiming the `End` row as table structure needs a declared table. |
| T18 | parse, write | Only the first workbook sheet enters the grid and output. |

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

Part 1 template-audit result: **74 collected, 58 passed, 16 strict xfailed**.
The strict failures are the documented future editor/declaration needs and the
unrelated pre-existing layout limits above.
