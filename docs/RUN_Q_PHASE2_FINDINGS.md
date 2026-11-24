# Run Q Phase 2 — findings from the real model answers

Source: the stored model answers in `local_docs/raw/<job>/` (jobs 40–84),
replayed through the current post-model pipeline by `tools/replay_raw.py`
(no model call, no key). The workbooks are in `local_docs/replay_out/<job>/`.
Jobs 68, 69 and 70 (smartsheet_mileage) have no stored answer and were not
replayed.

## What replay cannot do

Only the first slot call's answer is stored. Every later call (page recovery,
page chunks) has no answer, and replay counts it as failed, by name:

| job | file | calls with no stored answer |
|---|---|---:|
| 56 | carson_bank_6pg.pdf | 20 |
| 73 | fiserv_merchant_5pg.pdf | 10 |
| 46, 48 (×2), 51, 67, 84 | … | 4 each |
| 50, 54, 60, 74, 76, 78, 79, 81, 83 | … | 2 each |

A replayed document that needed recovery therefore shows fewer rows than
staging did. Rows missing for this reason are not counted below as a defect.

## Before / after per job (`tools/audit_exports.py`)

Before = the staging exports (`local_docs/rounds`, `local_docs/batch1_exports`).
After = the replay with the code at the start of Phase 2 (7bcea0d).

**Read the before column with care.** Several staging exports show 0 red cells
because a person accepted them (they show as `accepted` in the audit tool): job
66 had 97 accepted cells and replays as 97 Low, job 64 50 and 50, job 57 14 and
14, job 59 15 and 15. Accepted cells are not re-accepted on replay.

| job | low | amber | grey | placeholder | legend off | sum off | count off |
|---|---|---|---|---|---|---|---|
| 40 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 41–44 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 45 | 0→0 | 0→4 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 46 | 28→0 | 0→0 | 0→2 | 0→0 | 1→0 | 0→0 | 0→0 |
| 47 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 48 | 5→12 | 0→1 | 0→4 | 0→0 | 1→0 | 0→0 | 0→0 |
| 49 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 50 | 0→6 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 51 | 1→7 | 0→0 | 0→2 | 0→0 | 1→0 | 0→0 | 0→0 |
| 52, 53, 55 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 54 | 0→0 | 0→0 | 0→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 56 | 0→1 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 57 | 0→14 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 58 | 0→1 | 0→74 | 0→1 | 0→0 | 0→1 | 1→1 | 0→0 |
| 59 | 0→15 | 0→0 | 0→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 60 | 139→140 | 10→9 | 0→4 | 0→0 | 0→0 | 1→1 | 0→0 |
| 61 | 0→0 | 0→6 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 62 | 4→4 | 67→67 | 8→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 63 | 0→2 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 64 | 0→50 | 0→0 | 0→8 | 2→0 | 0→0 | 0→0 | 0→0 |
| 65 | 0→0 | 6→6 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 66 | 0→97 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 | 0→0 |
| 67 | 40→43 | 3→1 | 29→30 | 1→1 | 2→2 | 0→0 | 0→0 |
| 68–70 | not replayed (no stored answer) | | | | | | |
| 71 | 12→42 | 9→54 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 72 | 293→193 | 132→0 | 0→0 | 0→0 | 0→0 | 0→0 | 1→1 |
| 73 | 93→390 | 0→0 | 0→1 | 1→0 | 0→0 | 0→0 | 0→0 |
| 74 | 1→1 | 0→0 | 0→1 | 2→0 | 0→0 | 0→0 | 0→0 |
| 75 | 14→11 | 0→0 | 0→0 | 3→0 | 0→0 | 0→0 | 0→0 |
| 76 | 0→0 | 0→0 | 1→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 77, 80 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 78 | 2→2 | 0→0 | 6→1 | 0→0 | 0→0 | 0→0 | 0→0 |
| 79 | 6→6 | 0→0 | 26→9 | 4→0 | 0→0 | 0→0 | 0→0 |
| 81 | 1→0 | 0→0 | 21→4 | 0→0 | 0→0 | 0→0 | 0→0 |
| 82 | 19→6 | 0→13 | 0→0 | 0→0 | 0→0 | 0→0 | 0→0 |
| 83 | 20→6 | 0→13 | 0→4 | 0→0 | 0→0 | 0→0 | 0→0 |
| 84 | 104→13 | 0→0 | 0→6 | 1→1 | 0→0 | 0→0 | 0→0 |
| **total** | **782→1062** | **227→248** | **91→81** | **14→2** | | | |

Money stored as text is 9→9 (all job 58).

Job 73 rose from 93 to 390 Low. Staging stored the answers of 10 later calls
and the replay has none of them, so the replay keeps a different set of rows.
Its new Low cells come almost entirely from causes 1 and 2 below.

## Flagged cells by cause, ranked by count

Counted from the review comment on every red, amber and grey cell in the
replayed workbooks. Each cause was traced to its rule on the real page
geometry. A table row carries one row-level verdict, so one failed cell marks
every cell of its row. That is why a handful of rows makes hundreds of cells.

| # | cause | cells | jobs | kind |
|---|---|---:|---|---|
| 1 | **A long identifier is read as a phone number.** `_PHONE` has no digit boundaries, so any run of 10+ digits contains a "phone number". `_single_datum` then calls the cell "more than one piece of information". Batch `702000000803` (12 digits), invoice `08632520260515` (14) and `980104801-062326` are each one datum. | ~322 Low | 73 (33 rows: 297), 72 (2 rows: 25) | engine defect |
| 2 | **A repeated value's later copy skips the between-neighbours test.** `check_placement` looks at later copies of a value only for flush or overlap, not for the Q4 "between the neighbouring headings" rule. Job 73: `0.00` is printed under Chargebacks, Adjustments and Fees. The Fees copy (440–457) lies between `Fees` (417–437) and `Amount Processed` (471), but the first `0.00` is the one judged. Job 72: P.O. `26003221` is also glued into the invoice word `26003221AlexSysourat`. The real copy (125–158) sits between `P.O.` and `INV DATE`. | ~220 Low | 72 (10 rows: 131), 73 (11+ rows: ~90) | engine defect |
| 3 | **The scan's OCR reading is too thin to check against.** Tesseract read 106 words of the saltlake pay stub's scan page. The answer's lines are not in it, so they are "not found" and Low. The receipt photos (job 71) are the same. | 182 Low, 63 amber | 60 (140), 71 (42) | OCR reader (Q8) |
| 4 | **A value read from a picture on a native page.** The OU check stub prints the stub itself as an image (40% of page 1) on a page that has native text. The page is `native` and gets no OCR, because selective OCR needs a cover of at least 0.99. Every value is checked against a text layer that never held it, so all are "not found" and Low. | 97 Low | 66 | engine defect |
| 5 | **Undecided document boundary** ("May contain more than one document"). On tcnj_financials, page 2 is a second income statement ("Product" after "Service") with no reference to compare, so the flag is correct. | 75 amber, 45 Low, 22 grey | 58, 67 | correct, as designed |
| 6 | **A background panel is read as a redaction bar.** Fidelity pages 1–3 each draw two dark rectangles, each about 380×270 pt and just under half the page. About 500 printed words sit on them. `marks.native_bars` blanks every value "beneath" them. | 42 Low, 30 grey | 67 | engine defect |
| 7 | **Embedded OCR layer** (pre-OCR'd page, amber by design) | 79 amber, 4 Low | 62, 61, 65 | as designed |
| 8 | **Partly outlined page.** virtus_1099b draws its sample table as 788 glyph outlines next to 1,790 real characters. That is below the whole-page outlined rule (more paths than characters), so its values are Low, not unverified. | 65 Low | 64, 59 | engine gap |
| 9 | Grey: "Nothing was extracted, and something says a value was expected" | 51 grey | 79, 64, 84, 48, 60, 81 … | mixed: partly recovery calls with no stored answer |
| 10 | Placement in fidelity's two-column summary (`This Period` / `Year-to-Date`) | 37 Low | 67 | not traced |
| 11 | Ambiguous number format | 27 amber, 1 Low | 58 | as designed |
| 12 | Outlined text (ADP W-2) | 26 amber, 12 Low | 82, 83 | as designed (Q4) |
| — | small: payslip/receipt arithmetic (9), day/month swap (6), invoice check unreadable (4), currency decimals (2) | 21 | | as designed |

### Wrong or missing values

- **Answer key** (`local_docs/answers_extra.csv`, 13 values over 23 job
  documents). The replay has 22 of 23 correct. The one miss (job 44, "Recipient
  Address") holds `12 W Pine Street, Anytown, US 10000`, the street plus its
  city line, where the key has the street alone.
- **Missing rows on replay** come from the recovery calls that have no stored
  answer (table above). That is a replay limit, not a code cause.
- No other ground truth exists for jobs 40–84, so wrong values cannot be
  counted beyond the flags.

## Fixes chosen

These are the three largest **engine** causes: 1, 2 and 4. Cause 3 is larger
than cause 4, but it is the OCR reader's quality (Q8: psm 6 reads 312 words
of the same page against psm 3's 106, and still misses the table). Changing
the reader is outside this phase's scope, which allows no other items.

## Results

| cause | commit | change |
|---|---|---|
| 1 long identifier read as a phone | f40e025 | `_PHONE` needs a non-digit on each side. `Robert Chen 8005445555` in a name cell still fails (tested). |
| 2 repeated value / unbanded neighbour | 0f5e7cf | `check_placement` gives a value's later copies the between-neighbours test. `column_bands` also keeps the heading line's printed words, and `_between_neighbours` uses them **only for a side that has no banded neighbour at all**. A value really under its neighbour still fails (tested). |
| 4 a value read from a picture on a native page | 5e78732 | `text_layer.image_only_pages`: a native page whose image covers at least 0.2 of it with at most 2 text-layer words inside. A value there whose **only** failure is grounding becomes `unverified` with reason `image_only` ("Read from a picture on the page, please verify"). Any other failed check stands: job 66's payslip arithmetic still makes its 3 values Low. It shares one helper with the Q4 outlined-text rule. That helper now moves a row's columns to `_unchecked` instead of `_ungrounded`, because every reader paints an `_ungrounded` cell Low. Job 82/83's outlined rows had stayed red for that reason. |

Every test was written first and failed before its fix
(`tests/test_q_phase2_fixes.py`): unit tests use the real values and
coordinates, and the `_real` tests replay the stored answer.

### The same replay before and after the three fixes

| job | low | amber | grey |
|---|---|---|---|
| 66 | 97→3 | 0→94 | 0→0 |
| 72 | 193→37 | 0→0 | 0→0 |
| 73 | 390→12 | 0→0 | 1→1 |
| 82 | 6→0 | 13→19 | 0→0 |
| 83 | 6→0 | 13→19 | 4→4 |
| **all 42 replayed jobs** | **1062→422** | **248→354** | **81→81** |

No other job changed. Amber went up because cause 4's and the outlined
rows' cells now say "not checked, please verify" instead of "failed".

### Still open, by count (after)

1. OCR reading too thin on a scan (jobs 60, 71): 182 Low. This is Q8.
2. Partly outlined page (virtus, jobs 59 and 64): 65 Low.
3. Fidelity: a background panel read as a redaction bar (72 cells), plus a
   two-column summary flagged for placement (37).
4. Job 72 still has 37 grounding Lows (not traced in this phase).

### Final checks

| check | result |
|---|---|
| backend suite (once) | 5426 passed, 19 xfailed, 0 failed. The run started before the last part of 5e78732 (`_unchecked`) was written, so that part is covered by its own tests: `test_q_phase2_fixes.py` + `test_q4_false_low.py`, 27 passed |
| harness templated / no-template | 98.7% / 98.2%, structure 17/17 both, invented 0, misfiled 0, defect rate 0.0%. Unchanged |
| scoreboard (`tools/score_runs.py local_docs/job_records`) | scores the frozen staging job records, so the code does not move it: approve-only 1/4, purchase order 6/6 correct |

# Phase 3

Same rules as Run Q: one commit per item, tests first, no live model call, no
key, `.env` never read. Every engine fix was measured on the replay of the
stored real answers (jobs 40-84) with the answer key of item 8.

## The answer key (item 8, `tools/replay_key.py`, 8106306)

Built first, so each fix could be measured. Ground truth is only what a
PERSON did, read from `local_docs/raw/<job>/docs/*.json`:

* a value edited in review (`confidence: edited`, a row's `_edited` cells);
* every value a person left standing in a document they marked reviewed
  (`review.document_reviewed`, 20 documents);
* `local_docs/answers_extra.csv` (13 values read off the documents by hand),
  matched the way `tools/score_runs.py` matches them.

24 documents, 1,055 keyed values (was 13). `replay_key.py --save/--compare`
reports right / wrong / missing / extra per document.

**Read it with care.** "Reviewed" means a person accepted the document, not
that every value is right: job 64 (virtus 1099-B) was accepted with rows the
page contradicts (item 3). 229 of the 233 missing are carson_bank rows read
by page-recovery calls whose answers were never stored. Replay cannot
produce them, and they count as missing in every run alike.

## Before and after each fix

`low` / `page_check` count the review status of every value in all 42
replayed jobs (`app.core.review.document_values`). That is not the
workbook-cell count of the Phase 2 table above.

| item | commit | answer key right / wrong / missing / extra | replay |
|---|---|---|---|
| baseline (60eff8e) | | 819 / 3 / 233 / 0 | |
| 2 Q8 OCR quality | 535be92 | 819 / 3 / 233 / 0 | low 413, page_check 38: jobs 82/83 one page item each, 38 cells amber -> page_check |
| 3 Q7 rows vs records | 02284e9 | 819 / 3 / 233 / 0 | 16 row_mismatch flags, all job 64 |
| 4 Q11 template fit | 1478c54 | 819 / 3 / 233 / 0 | low 397. Ignored forms named in jobs 53, 54, 76, 78; "does not look like a Purchase Order" in job 59 only |
| 5 Q10 spacing/money | bc7b903 | 819 / 3 / 233 / 0 | glued words 0 (jobs 56, 78); money stored as text 9 -> 0 (job 58) |
| 6 Q4 (e)-(g) | e0ba07e | 819 / 3 / 233 / **1** | low 397 -> 381; same-value clears 9 -> 5 |

The key's values never moved because items 2-6 change flags and levels,
not the values the model gave. The one new "extra" is tcnj's "Total
liabilities and owners' equity" = $13,060, which the engine used to clear
as a copy of "Total assets". The page prints both totals as 13,060 (the
document's own attention text says so), so the kept value is right and
the key's empty slot was the old engine's clear.

The 3 wrong: job 44 Recipient Address (street plus city line, where the key
has the street alone); job 50 mcguire Employee Name (`Kim` where the
accepted value is `Kim McGuire`, so the replay truncates); job 56 carson
Bank Name, which a person edited to `Carson Bank Of So and so` (the replay
has `Carson Bank`). The Memo a person corrected to `13.17` on job 56 matches.

## What each item did

1. **UI1 rework** (60eff8e). New extraction sits in the top action bar
   beside Download Excel. It opens the same fresh page as the top-right
   button: no files, no result, template picker reset. The inline template
   choice and the re-run call are gone from the frontend (`extractApi.rerun`
   removed). The backend route `POST /api/jobs/{id}/rerun` still exists, and
   no UI calls it.
2. **Q8 / cause 3** (535be92).
   (a) A money or number slot whose figure holds letters or symbols among its
   digits is Low, flagged with the OCR-confusable reading (`1O,5S0.00`:
   reading `10,550.00`). It is never rewritten. It fires on no stored answer.
   (b) An embedded OCR layer was already grounded against. That is now pinned
   on the real utah_paystub_2.
   (c) An outlined page (ADP W-2) raises ONE "verify this page against the
   image" item. Its values keep level `unverified`, read as `page_check`
   (no fill, a note), with no per-cell flag. The OCR seam was not changed:
   Tesseract reads that outlined text as noise.
3. **Q7** (02284e9). `engine/outline_check.py`: virtus 1099-B draws its
   records as outlines, and OCR reads them as noise even at 600 dpi. So rows
   are checked against the page's geometry:
   - the records (rows of check boxes, marked or not; checkbox columns by x);
   - where each record prints anything, aligned to the template's columns by
     their heading words.

   A value where the record prints nothing is Low (`row_mismatch`), named as
   computed when it equals arithmetic of the row. So is a printed value left
   empty, or a box answered differently. The stored answer gets 16 such
   flags; a correct answer gets none (tested).
4. **Q11** (1478c54). `engine/template_fit.py`:
   - forms the document prints that the template does not cover are named in
     a visible note and flag;
   - a template whose type the page does not read as gets one attention
     item: "This does not look like a Purchase Order".
5. **Q10** (bc7b903). Started from `wip/run-q-q10` (ab52506), merged and
   finished, with real replay tests added.
6. **Q4 (e)-(g)** (e0ba07e). (e) a form box's value printed below its label;
   (f) a lone `$` at a money box's edge is not a gutter; (g) an OCR date
   missing a separator. Found on the way: the same-value rule then cleared a
   W-2's boxes 1 and 3 ($28,000, also box 5's). A figure printed once per
   slot, each slot quoting its own text, is no longer cleared. Job 79 box 4
   (a quote interleaving two boxes' labels) stays Low as a strict xfail.
7. **UI3** (276843b). While a job is open, "Template used" replaces the
   picker. The empty state previews the job's template. Download ZIP follows
   the job's document count. The status line uses plain words.

## Still open

- Q8: a scan's thin OCR reading (jobs 60, 71). The reader was not changed.
- Q7: rows drawn as outlines are only checked where each record carries
  check boxes; a plain outlined table gets no verdict.
- Q4: job 79 box 4 (strict xfail); job 62 utah_paystub_2's interleaved
  two-column fields (Position/Title, Employee Address).
- The no-template harness RAW reads 59.4% where CLAUDE.md records 70.1%
  (Run A). Phase 2's end commit (f74b86d) reads the same 59.4%, so Phase 3
  did not move it. The cause was not traced.

## Final checks (once)

| check | result |
|---|---|
| backend suite (once, at 276843b) | 5481 passed, 3 failed, 20 xfailed. The 3 (test_cheque_cross_check) were one regression from item 2: "Amount in Words" read `00/100` as a symbol inside a figure. Fixed in 162452f (an amount written in words is not a figure); the cheque and Q8 files re-run, 32 passed. The full suite was not run a second time |
| harness templated / no-template | 98.7% / 98.2%, structure 17/17 both, invented 0, misfiled 0. Unchanged. RAW 48.0% / 59.4% |
| frontend | tests 97 pass, type-check clean, build clean (UI3); UI1 the same at its commit |
| scoreboard (`tools/score_runs.py local_docs/job_records`) | frozen staging records, unchanged: approve-only 1/4, purchase order 6/6 |
