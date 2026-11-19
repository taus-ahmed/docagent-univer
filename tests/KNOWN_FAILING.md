# Strict acceptance xfails

Every item below is `xfail(strict=True)`. These are real application gaps, not
adapter/name mismatches. A future implementation that makes one pass will fail
as XPASS until its marker and this row are removed.

| Gap | Strict test | Implementation evidence | Observed failure |
| --- | --- | --- | --- |
| C1 merge inside a repeating band | `test_c1_merge_inside_a_band_survives_the_export` | `excel_cells._apply_template_merges` skips every merge intersecting a band instead of only unsafe cross-boundary merges. | With one extracted row and template merge `B4:C4`, the exported workbook has no `B4:C4` merge. |
| C3 numeric percentage | `test_c3_percentage_is_a_number_with_a_percent_format` | `excel_cells.coerce_cell_value` rejects `Amount.percent` values from its numeric path. | `Percentage = "12.5%"` is stored as a string rather than numeric `0.125` with a percent format. |
| C4 table followed by notes and two blank rows | `test_c4_notes_still_end_the_table_when_two_blank_rows_follow_them` | `template_shape.compute_shape` lets any later pair of blanks override the first nonblank row after a reserved band. | `Notes` at row 5, blank rows 6-7, and `Prepared By` at row 8 produces table `end_row=6` (zero-based) instead of `3`; the notes and blanks are swallowed. |
| C6 unique quote line lacks the value | `test_c6_unique_quote_without_value_does_not_box_the_wrong_line` | `review_highlights.find_box` immediately returns a uniquely matching quote line, without checking whether it contains the value or searching elsewhere. | Quote `Invoice total` at y=10 is highlighted even though value `$123.45` is alone at y=40. |
| C7 non-US transit number | `test_c7_non_us_transit_number_is_not_failed_as_an_aba_routing_number` | `cheque_validators.bottom_line` applies the US ABA checksum to every routing/transit field. | Legitimate transit number `12345` is flagged `routing_checksum_failed`. |
| C7 checksum-only routing validation | `test_c7_nine_digits_that_are_not_a_routing_number_are_rejected` | `cheque_validators.aba_is_valid` has no nonzero/plausibility guard. | `000000000` passes as a valid routing number. |
| C7 swap hidden by a checksum coincidence | `test_c7_checksum_valid_account_number_does_not_hide_a_swap` | `cheque_validators.bottom_line` uses checksum validity as the swap detector and ignores unambiguous MICR sentinels when both values pass. | MICR `A021000021A C011401533C 1234D` with stored routing `011401533` and account `021000021` yields no `possible_swap`. |

## Harness regression

`test_harness_reader_does_not_hide_a_duplicate_total_row` is also a strict
xfail. The Run C `sheet_reader` tail matcher treats an erroneous duplicate
`Total` row inside a reserved band as the scalar template tail. The direct
openpyxl assertion sees both `Total` rows; the new reader reports one clean
table row and one scalar total, while the pre-Run C reader reports the extra
table row. This is a test-tool blind spot, not an application defect.

Run C removed the three A6 rows (compact reserved bands, exactly three blank
rows between documents, clean default columns): `excel_slot._write_slot_excel`
writes each band with its actual row count, `GAP_BETWEEN_DOCS = 3`, and the
Source / Review status columns are opt-in (`include_audit`). The markers came
off in the same commit as the fix.

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
