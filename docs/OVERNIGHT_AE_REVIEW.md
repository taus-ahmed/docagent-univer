# Overnight A-E adversarial review

Reviewed `cd2dbd4..HEAD` on 2026-11-20. The executable review is
`tests/test_overnight_ae_adversarial_review.py`. It uses scripted model
answers through `run_slot_extraction`, the local real-document corpus, the
production exporter, and local HTTP fixtures. No provider or remote service is
called.

## Verdicts

| Fix | Verdict | Adversarial result and responsible location |
| --- | --- | --- |
| A1 ownership | **Holds with gap** | The real Pitt W-2 control keeps equal Box 3/5 wages, keeps `E 4107.00` in Box 12, and clears the Box 11 copy. **Gap:** an X exactly between two close option spans is assigned to the first option and can replace the model's other choice. `ownership.py:223-226` uses `min(...)` without a tie or confidence margin. |
| A2 repeated box entries | **Holds** | The real Box 12 `E` and `W` rows both survive; Box 14's `52.00 X` does not enter Box 12 and is visibly flagged as having no slot. The boundary is `ownership.py:475-503`, called at `slot_extractor.py:2405-2413`. |
| A3 types and formatting | **Holds** | Wages remain numeric money, counts/hours/years/percentages remain numeric with their correct formats, identifiers with spaces/dashes remain text, and negative/parenthesized money retains sign and two decimals. The decisions are in `app/services/excel_cells.py:176-272` and `523-571`. |
| A4 lost-page recovery | **Holds with gap** | The real Mammoth page 2 recovers in order, its repeated header is excluded, and no duplicate is introduced; a truly empty page is not called. **Gap:** with five eligible lost pages and the four-call cap, the fifth page can remain wholly absent with no attention item. `slot_extractor.py:678` slices `sorted(want)[:cap]`; the aggregate shortfall thresholds in `source_inventory.py:558-563` need not fire. `PAGE_RECOVERY_MAX_CALLS` is also not declared in `app/config.py`, so `llm_contract.setting` always falls back to four in the normal settings path. |
| A5 empty form title | **Holds** | One real `Form 1099-INT` title fills the slot. The brokerage page's several distinct titles leave it empty and flagged with the title list, so no title is guessed. See `slot_extractor.py:2368-2387` and `source_inventory.py:571-601`. |
| A6 consistency and fragments | **Broken** | Temperature zero and the known one-entity Pitt fragments hold. **Failure:** two real rows (`Checking-A 100.00`, `Savings-B 250.00`) become one row, with Savings-B's credit attached to Checking-A. `ownership.py:521-542` treats a first-row key plus later keyless/disjoint columns as sufficient proof of one entity. |
| B1 grounding normalization | **Broken** | Whole-number matching holds (`70.00` does not ground inside `170.00`), dot leaders hold, and a value not printed anywhere stays low. **Failure:** Opening Balance `170.00` with an invented/unfound quote is reanchored to the Closing Balance line and graded high, though Opening Balance prints `100.00`. `slot_extractor.py:2161-2179` searches the whole document and falls back to the first value line; the shared word `balance` makes the wrong row look label-related. |
| B2 column placement | **Broken** | A plain amount under the Description column is flagged. **Failure:** if Description itself is `Service 70.00` and Amount is also `70.00`, placement is skipped even though the page prints the amount only under Description. `text_layer.py:1890-1894` exempts every value found inside another cell; `_inside_another_cell` at `1933-1947` does not exclude numeric cells. |
| B3 completeness | **Broken** | Real blank fillable boxes remain quiet. **Failures:** one unmatched filled widget (`ZX-9`) is silent because widget reporting requires at least three misses and half the widgets (`source_inventory.py:522-528`); one prose value next to its full label (`Employee Name Alice Rivera`) is silent because `_counts_as_missed` accepts only digits (`371`, `393-410`) and the aggregate field reason needs a majority (`625-630`). |
| B4 Legend counts | **Holds** | The current writer's Legend equals marked cells across two document blocks after one flagged empty cell is human-edited. The older staging exports still reproduce the pre-fix evidence: jobs 46, 48, and 51 disagree, while the other 13 agree. Current marking is in `app/services/excel_slot.py`; the independent counter is `tests/legend_check.py`. |
| C F-rules | **Holds** | Representative pipeline controls pass for F2, F4, F5, E9, E11, E12, including a trailing-minus amount and refusal to self-certify a cross-column address. The full existing coverage remains in `tests/test_run_f_adversarial_review.py`. |
| D template structure | **Holds** | `Approver 2` is not a period matrix, a long `Total amounts shown in USD` note is not a field, and two money tables one blank column apart remain separate. F10 still has exactly its two formula warnings and T9 names Item/Debit/Credit. See `template_shape.py:156-193`, `793-799`, `1120-1177`. |
| E review refresh and navigation | **Holds** | Edit, accept/correct/confirm-empty/add-row success paths invalidate the review, `job-results`, job, and jobs queries; the Extract page consumes `job-results`. Local HTTP controls confirm GET `/results` and the exported workbook agree after accept, confirmed empty, and add row. Save failures render an error toast. Previous/next page navigation and page-following selection are wired through `reviewPages`. See `frontend/lib/reviewRefresh.ts`, `ResultsGrid.tsx:153-157,302-340`, and `ReviewPanel.tsx:121-234,268-343`. |

## Severity 1: silent wrong value

1. **B1 wrong-row reanchoring.** Input: Opening `100.00`, Closing `170.00`; model says Opening `170.00` with a quote the page does not contain. Actual: `170.00` is retained at high confidence with no flag. This is the most direct approve-only failure: the wrong value is present and green.

2. **B2 numeric placement bypass.** Input row: Description `Service 70.00`; the page has no Amount-column occurrence, but the answer also fills Amount `70.00`. Actual: both cells survive and Amount has no different-column flag.

3. **A1 checkbox tie.** Input: Box 13 Alpha and Beta one point either side of the X centre; the scripted answer selects Beta. Actual: ownership moves the X to Alpha with no ambiguity flag.

## Severity 2: correct value dropped or merged

1. **A4 capped page recovery drops correct rows.** Input: 100 rows on page 1 and two rows on each of pages 2-6; pages 2-6 are all eligible for targeted recovery. Actual: pages 2-5 recover, page 6 does not, output has 108 of 110 rows, and no attention item names page 6.

2. **A6 fragment merge crosses entities.** Input rows: `Checking-A / Debit 100.00` and a real `Savings-B / Credit 250.00` line whose key was omitted by the model. Actual: one row, `Checking-A / Debit 100.00 / Credit 250.00`. The correct credit is merged into the wrong account and the Savings row disappears.

3. **B3 single missed widget.** Input: filled widget `Client Reference = ZX-9`, no matching slot/cell. Actual: no completeness reason. A reviewer can approve without seeing the omitted correct value.

4. **B3 single missed prose field.** Input: text-layer line `Employee Name Alice Rivera`, empty Employee Name answer. Actual: no completeness reason because the nearby value has no digit and one miss does not reach the aggregate threshold.

No severity 3-only finding was added.

## Test result

```text
pytest -q -rxX tests/test_overnight_ae_adversarial_review.py
22 passed, 7 xfailed
```

All seven xfails are strict and are registered in `tests/KNOWN_FAILING.md`.
