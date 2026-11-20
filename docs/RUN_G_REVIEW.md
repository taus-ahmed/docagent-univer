# Run G review

Reviewed the `cd2dbd4` tree locally. No model provider or remote service was
called.

## Changed old tests

| Test change | Verdict | Why |
| --- | --- | --- |
| `test_run_c_adversarial.py`: Date removed from the identifier/text parameter set and tested as 15 January 2024 | Legitimate | The old identifier assertions remain. The replacement is stronger for the changed requirement: exact `datetime(2024, 1, 15)`, `is_date`, and `mm/dd/yyyy`. Ambiguous-date text behavior is separately pinned in `test_run_g_dates.py`. |
| `test_run_c_export.py`: same Date change | Legitimate | It changes only the owner's date ruling and asserts the real Excel type, value, and display format. It does not relax the other identifier/text cases. |
| `test_run_a_review_edits.py`: “once settled” now confirms the flagged empty slot | Legitimate | A flagged empty value is unresolved under G4 until it receives `confirmed_empty`. Merely accepting another field and settling completeness must not silently settle it. |
| `test_batch_end_to_end.py`: real dates excluded from numeric-contamination fingerprints and checked separately | Legitimate | A real Excel date is numerically stored, so treating it as a contaminating amount is wrong. The new check ties each date cell to a date printed by that sheet's one source document; the suite separately pins ambiguous dates as text. |

None of the four changes weakens its surrounding contract.

## G4 API attacks

`tests/test_run_g_adversarial_review.py` exercises the real HTTP routes and
downloads a workbook after every material state change.

| Attack | Current result |
| --- | --- |
| accepted / corrected / empty in unusual orders, exporting between actions | Pass |
| correct a value, then confirm that same slot empty | Pass |
| accept one table cell without accepting its row | Pass |
| add a row, retain and re-flag a declared total, then correct the total | Pass |
| approve with an unresolved value or completeness reason | Pass: both return 409 |
| history order and complete field, row, attention, and document events | Pass |
| second tenant on review, add-row, history, approve, and export routes | Pass: every route returns 404 |
| owner 1099 Form Type correction, fresh results read, then export | Pass at API level |

The owner reproduction uses the `Correct` disposition request, keeps the
ambiguity note and an open completeness reason, then independently reads
`GET /results` and downloads Excel. Both contain the corrected Form Type on
this tree, so there is no strict xfail for this reproduction.

## G5 frontend findings

The request builders themselves match the server contract: corrections carry
`value`, table dispositions carry `column` and stable `row_id`, add-row sends
only the table's columns plus optional `attention_id`, and completeness choices
use `dispositions`.

The refresh/click path has these mismatches with the manual check:

1. `ReviewPanel.tsx:126-145` sends a correction through `reviewApi.mark`, but
   unlike the ordinary edit path at lines 176-198 it never updates
   `result.extracted_data`. The mark response type at `api.ts:590-600` does not
   include the updated extraction either.
2. `ResultsGrid.tsx:152-154` defines `onChanged` as invalidating only the
   `review` query. Its displayed values still come from the unchanged `results`
   prop at lines 156-199. A corrected value can therefore snap back in the
   main grid even though the server saved it. Add-row has the same stale-copy
   problem for the Rows panel.
3. Status is also built from the original `doc.needs_review` at line 177, and
   `StatusCell` treats that stale Boolean as authoritative at lines 65-73.
   Settling the last item cannot make the grid say `OK` until the parent results
   are reloaded.
4. Completeness and document-review clicks call `onChanged()` directly at
   `ReviewPanel.tsx:216` and `:227`, not the `changed()` helper that reloads an
   open History panel. Those event types cannot appear live while History is
   open.

The likely location of the reported UI revert is items 1-2: the server stores
the correction, the review query refreshes, but the grid continues rendering
the pre-correction results object. The API reproduction shows the current
server and export writer retain the edit, so the reported downloaded-Excel
revert was not reproduced at the API boundary. A later stale client action is
the remaining likely trigger; the server's whole-document reconciliation is
intended to protect against it.

## Batch-1 defect contracts

`tests/test_batch1_real_defects.py` runs local scripted answers through
`run_slot_extraction` and the production workbook writer. Strict failures are
registered in `tests/KNOWN_FAILING.md`.

| Item | Current result | Observed current behavior |
| --- | --- | --- |
| 1. Invoice Remit To Bank | Strict xfail | Vendor name survives in an unprinted bank slot. |
| 2. Pitt W-2 boxes 11 and 13 | Strict xfail | `4107` survives in Box 11; box placement is not enforced. |
| 3. Pitt Box 14 `52.00 14X` | Strict xfail | It survives as an uncoded Box 12 row. |
| 4. Locality, control number, money | Strict xfail | The control-number space is not restored, locality exports numeric, and whole-number money uses `#,##0` instead of two decimals. |
| 5. Mammoth page 2 | Strict xfail | Thirty-seven page-1 rows are silently accepted without recovery or a page/row completeness reason. |
| 6. Combined/single 1099 and Pitt row parity | Strict xfail | Form-Type flagging and combined/single parity pass; the three partial state/local rows remain silently split. |
| 7. False Low flags | Strict xfail | Thirteen dot-leader values, header-only quotes, joined address lines, statement descriptions, and Kim McGuire still produce false Low states. Negative misplaced/absent controls still flag. |
| 8. False completeness | Strict xfail | The blank fillable W-2 still reports about two missing line items and absent rows; the 1099 and real missed-value control pass. |
| 9. Legend versus marks | Strict xfail | Jobs 46, 48, and 51 claim 3, 12, and 2 empty flags while painting zero grey cells. |
| 10. Dates | Strict xfail | Invoice/PO/receipt dates pass and ambiguous dates stay text; statement-period dates in jobs 40, 41, and 46 remain text because those labels are not classified as date slots. |
