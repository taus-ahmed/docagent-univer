# Strict acceptance xfails

Every item in the first table is `xfail(strict=True)`. These are real
application gaps, not adapter/name mismatches. A future implementation that
makes one pass will fail as XPASS until its marker and this row are removed.

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| Run D D6: gapped matrix heading becomes fields | `test_d6_a_matrix_heading_may_have_one_intentionally_empty_cell` | Heading detection now requires every heading cell between the first and last text to be non-empty. | `Line item | _ | 2026` over `Revenue`/`Expenses` loses C2/C3 and invents B1/D1 scalar slots. |
| Run D D7: one table split at a spacer column | `test_d7_a_blank_spacer_inside_one_table_does_not_make_two_tables` | Header detection splits every contiguous text run into a separate band. | `Date | Description | _ | Debit | Balance` becomes two tables instead of one table with an intentional visual spacer. |
| Run D D8: side note becomes a field | `test_d8_a_note_beside_a_table_is_not_a_scalar_field` | A pure label list at the right edge implies a value column even when the text is a static note. | `Amounts in USD` beside a three-column table creates bogus slot F2. |
| Run D D10: decorative merge becomes a slot | `test_d10_a_merged_section_heading_does_not_own_a_decorative_empty_merge` | Any empty merge immediately after a merged text cell is assigned to that text. | Merged heading `Invoice Summary` over A1:B1 plus decorative empty C1:D1 creates field C1. |
| Run D D11: legitimate `TBD` label erased | `test_d11_an_exact_tbd_label_can_be_real_template_text` | Exact `TBD` is unconditionally converted to an empty placeholder. | A row label `TBD` disappears and its B1 field slot is lost. (`Total due TBD` is correctly left alone.) |
| Run D D13: warnings on valid layouts | `test_d13_owner_approved_header_only_tables_do_not_need_a_warning`, `test_d13_a_valid_horizontal_field_pair_is_not_warning_noise` | The warning pass does not account for the owner-approved ten-row header-only rule and warns whenever an implied right slot also has an unused cell below. | Valid header-only tables and valid horizontal fields produce warning noise. The committed audit finds 36 warnings, 33 of them on layouts that are otherwise fine under the recorded rules. |

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
