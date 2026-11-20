# Strict acceptance xfails

Every item in the first table is `xfail(strict=True)`. These are real
application gaps, not adapter/name mismatches. A future implementation that
makes one pass will fail as XPASS until its marker and this row are removed.

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| Batch1 item 1: unprinted remit bank | `test_01_invoice_vendor_name_is_not_invented_as_remit_bank` | The post-model checks accept a grounded value without checking that its source is the requested bank slot. | `Harwood Design Studio Ltd` survives in `Remit To Bank` although the invoice prints no bank name. |
| Batch1 item 2: W-2 cross-box values and marks | `test_02_w2_cross_box_value_and_checkbox_are_not_accepted` | Grounding validates that the characters occur, but not that `E 4107.00` belongs to Box 12 or that the one X is under Retirement Plan. | Box 11 keeps `4107`; the statutory mark is not reliably separated from the retirement mark. |
| Batch1 item 3: Box 14 value moved into Box 12 | `test_03_box14_entry_never_moves_to_an_uncoded_box12_row` | A table row with an empty code and grounded amount is accepted without a required-code/band check. | `52.00 14X` survives as an uncoded Box 12 row. |
| Batch1 item 4: exact identifiers and money format | `test_04_identifiers_remain_text_and_money_keeps_two_decimals` | The post-model/export seam does not repair a printed identifier separator, classify numeric locality as text, or retain cents for whole-number money. | Control number stays `0000005712UUQ`, locality becomes numeric `700102`, and `4107.00` exports with `#,##0` rather than `#,##0.00`. |
| Batch1 item 5: second statement page omitted | `test_05_page_one_only_statement_is_recovered_or_needs_attention` | Completeness accepts a 37-row page-one answer even though page 2 prints 11 more dated rows. | The document is not recovered and has no page/row completeness reason. |
| Batch1 item 6: split state/local row | `test_06c_split_state_local_row_is_merged_or_visibly_flagged` | Partial rows in one state/local band are neither merged nor subjected to a row-completeness rule. | One printed state/local record remains three silent rows. |
| Batch1 item 7: false Low flags | `test_07_correct_values_are_not_low_but_real_errors_still_are` | Grounding/placement normalization does not tolerate dot leaders, joined line breaks, header-only quotes, and several form/table geometries. | Correct brokerage, bank-summary, address, statement-description, and W-2 name values are marked Low; the same test proves real errors still flag. |
| Batch1 item 8: false completeness on fillable forms | `test_08_fillable_blank_boxes_do_not_create_false_completeness_reasons` | Source row inventory treats blank W-2 form boxes/instructions as missing line items. | The blank fillable W-2 says “about 2 line items” and “did not include the rows.” |
| Batch1 item 9: Legend counts | `test_09_each_real_legend_count_equals_cells_actually_marked` | Legend totals include empty-flagged values for which the result block paints no grey cell. | Jobs 46, 48, and 51 report 3, 12, and 2 empty-flagged values but paint zero grey cells. |
| Batch1 item 10: real Excel dates | `test_10_date_slots_export_as_real_dates` | `slot_type` does not classify statement-period start/end labels as date slots. | Jobs 40, 41, and 46 keep unambiguous period dates as text; the other mocked date jobs already write real dates. |

Run G (G4) removed REVIEW RULES 1, 2, 3, 4 and 8 in one commit, because
they share one change: a review value entry carries `disposition`
(`accepted_as_is` / `corrected` / `confirmed_empty`), stored on the value's
mark and logged in `edit_log`; a table disposition marks one cell
(`_reviewed_cells`); a confirmed-empty slot and a corrected value export with
no warning comment. REVIEW RULE 7 came off with `GET .../history`
(`routes/review.py::document_history`). REVIEW RULE 5 came off with
`POST .../rows/{table}` (`routes/review.py::add_row`): a stable `_row_id`, an
`add_row` event, the row in the exported band plus a "Rows added by hand"
list on the Legend, and every total-labelled slot RE-FLAGGED (never
rewritten) when the rows no longer sum to it. REVIEW RULE 6 came off with
`review.unsettled`: one count (unresolved values + open completeness reasons)
behind the stored `reviewed`/`needs_review` columns, every edit, the approve
route (refused while anything is owed; otherwise it writes the same document
mark) and the export's `_DRAFT` name. All eight review rules now pass.

The eight rows above are the target review contract in
`tests/test_review_flow_spec.py`. Each marker names `REVIEW RULE 1` through
`REVIEW RULE 8`; an implementation that satisfies a rule will XPASS and force
an explicit marker/registry update.

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

## Batch 2 real-document failure classes

All entries are exercised through `run_slot_extraction` by
`tests/test_batch2_failure_classes.py`, using local PDFs and scripted model
answers. No provider or remote service is involved.

| Rule gap | Strict test(s) | Observed application failure |
| --- | --- | --- |

All six strict xfails above came off in Run F (one commit each: test_01 with
the E9 copied-column check, F1 blank form, F2 explainer pages, F3 specimen
placeholders, F4 callout numbers, F5 statements), `engine/real_data.py`.

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
