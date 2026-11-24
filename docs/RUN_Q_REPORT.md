# Run Q report — fix/review-fixes

## Start

- Merged `origin/review/run-n` (3a0857a). Its helper already patches the
  real cap lookup, `llm_contract.setting("PAGE_RECOVERY_MAX_CALLS", 4)`
  (`slot_extractor.py:650`); there is no `Settings` attribute of that name.
  All 7 strict xfails fail under `--runxfail` on the assertion describing the
  defect (`'high' == 'low'`, `'low' == 'high'`, `'ambig' not in …`, `1 == 2` ×2,
  `'page 3' in ''`, `'rev c' not in …`), with no setup errors.
- Baseline suite: no failures, xfails only.

## Q0 — raw-response replay

- The raw answer is `document_results.raw_llm_response`, written in
  `services/job_worker.py` from `result.extraction_response.raw_text` and
  purged after `RAW_RESPONSE_RETENTION_DAYS` (default 7) by
  `core/raw_retention.py`. **Only the first slot call's answer is kept**:
  page-recovery calls, page chunks of a heavy document and template inference
  are not stored. Replay answers inference from the stored
  `inferred_template` and fails (counts, prints) every other call it has no
  answer for, so a replayed document that needed recovery says it was not
  recovered. It does not pretend.
- `tools/export_raw_responses.py <ids>`: `DATABASE_URL` from the
  environment only, never printed (errors print the exception class only),
  SELECT-only inside `SET TRANSACTION READ ONLY` on PostgreSQL. It writes
  `local_docs/raw/<id>/{job,template}.json` and `docs/<doc_id>.json`.
- `tools/replay_raw.py <ids>` runs `extractor.run_extraction` with the
  stored answer and the real writers, writing `local_docs/replay_out/`.
- `tools/live_corpus.py`: offline plan by default; `--live` needs
  `GEMINI_API_KEY`; caps at 60 calls and $1. A capped call FAILS and is never
  silently empty. It covers the 29 jobs 56–84 listed in
  `tools/live_corpus_manifest.json`; 68–70 are smartsheet_mileage. **Not run.**
- Test mode: `tests/run_q_support.py`. Each Run Q reproduction is named
  `…_reconstructed` (a mock rebuilt from the export) and has a `…_real` twin
  that reads `local_docs/raw/<job>` and skips with a reason when it is absent.

## Q15 — before scoreboard (`tools/audit_exports.py`)

`tools/audit_exports.py local_docs/rounds local_docs/batch1_exports`, at the
start of Run Q (exports as produced by the staging build):

```
file                                    low    amber     grey accepted placehol money_te  legend sum count
job_56_results.xlsx                       0        0        0       82        0        0       0   1     0
job_57_results.xlsx                       0        0        0       14        0        0       0   0     0
job_58_results.xlsx                       0        0        0        1        0        9       0   1     0
job_59_results.xlsx                       0        0        0       15        0        0       0   0     0
job_60_results.xlsx                     139       10        0        0        0        0       0   1     0
job_61_results.xlsx                       0        0        0        0        0        0       0   0     0
job_62_results.xlsx                       4       67        8        0        0        0       0   0     0
job_63_results.xlsx                       0        0        0        1        0        0       0   0     0
job_64_results.xlsx                       0        0        0       50        2        0       0   0     0
job_65_results.xlsx                       0        6        0        0        0        0       0   0     0
job_66_results.xlsx                       0        0        0       97        0        0       0   1     0
job_67_results.xlsx                      40        3       29        0        1        0       2   0     0
job_71_results.xlsx                      12        9        0       25        0        0       0   0     0
job_72_results.xlsx                     293      132        0      141        0        0       0   0     1
job_73_results.xlsx                      93        0        0        0        1        0       0   0     0
job_74_results.xlsx                       1        0        0        0        2        0       0   0     0
job_75_results.xlsx                      14        0        0        0        3        0       0   0     0
job_76_results.xlsx                       0        0        1        0        0        0       0   0     0
job_77_results.xlsx                       0        0        0        0        0        0       0   0     0
job_78_results.xlsx                       2        0        6        0        0        0       0   0     0
job_79_results.xlsx                       6        0       26        0        4        0       0   0     0
job_80_results.xlsx                       0        0        0        0        0        0       0   0     0
job_81_results.xlsx                       1        0       21        0        0        0       0   0     0
job_82_results.xlsx                      19        0        0        0        0        0       0   0     0
job_83_results.xlsx                      20        0        0        0        0        0       0   0     0
job_84_results.xlsx                     104        0        0        0        1        0       0   0     0
job_40_results.xlsx                       0        0        0        7        0        0       0   1     0
job_41_results.xlsx                       0        0        0        0        0        0       0   0     0
job_42_results.xlsx                       0        0        0        2        0        0       0   0     0
job_43_results.xlsx                       0        0        0        0        0        0       0   0     0
job_44_results.xlsx                       0        0        0        0        0        0       0   0     0
job_45_results.xlsx                       0        0        0        0        0        0       0   0     0
job_46_results.xlsx                      28        0        0        0        0        0       1   0     0
job_47_results.xlsx                       0        0        0        0        0        0       0   1     0
job_48_results.xlsx                       5        0        0        0        0        0       1   0     0
job_49_results.xlsx                       0        0        0        0        0        0       0   0     0
job_50_results.xlsx                       0        0        0        3        0        0       0   0     0
job_51_results.xlsx                       1        0        0        0        0        0       1   0     0
job_52_results.xlsx                       0        0        0        0        0        0       0   0     0
job_53_results.xlsx                       0        0        0       11        0        0       0   0     0
job_54_results.xlsx                       0        0        0       11        0        0       0   0     0
job_55_results.xlsx                       0        0        0        0        0        0       0   0     0
TOTAL (42 files)                        782      227       91      460       14        9       5   6     1
```

Columns: red/amber/grey cells; values accepted after a Low flag;
placeholder text left as a value; money stored as text; Legend counts that
disagree with the marks; Total rows that disagree with the sum of the rows
above (heuristic); printed counts that disagree with the table (heuristic).
Two findings are real and need nothing more than the tool: job 67's Legend
says Low 31 but 40 cells are red, and job 72's "Total Invoices Count 90"
sits against a 22-row table. The sum/count columns are heuristics. A
statement's "Total Deposits" is not the sum of the summary lines above it,
so read them as pointers, not verdicts.

---

# Phase 1 (Q9, Q1, Q2, Q4, Q5, Q12, UI1, UI2, Q15)

Phase 1 covers only these items. Q3, Q6, Q7, Q13, UI3 and the N-gap fixes
were committed earlier in Run Q. Q8, Q10, Q11 and Q14 are **not done** and
stay unchecked. Q10 had uncommitted work, and Phase 1 did not finish it:
it is parked as one WIP commit on the local branch `wip/run-q-q10`, which
is not pushed and not merged.

## What was done

| item | commit | what changed |
|---|---|---|
| Q1 lost pages | 494819c, c974e94, 5d8ec49 | (a) job 72's lost pages came from a document split. A footer that ends in its own page number now vetoes the cut. Recovery runs with or without a template. (b) a printed row count ("Total Invoices Count 90", "5 INVOICES", "Number of Invoices: 5") that the rows fall short of raises a completeness reason naming both numbers. (c) N6: a page past the recovery cap, or one holding under half its rows, is named and set NEEDS_ATTENTION |
| Q2 side-by-side | c153603 | `engine/column_groups.py`: a heading whose words repeat k≥2 times (`Number Date Amount` ×3) is a grouped table. The prompt and the page-recovery request say so, and recovery counts k records per printed line. A grouped record that no row carries raises `[side-by-side]`, naming the page's own count and the missing records. DAILY BALANCE lines are left out of a transaction table with a note. A row read below a different printed account number (job 56, Account 3216) gets `[other account]` and is marked Low |
| Q4 false-low | afe8caf, 69cf3aa (N2, N4), 265503f | (a) a page that draws its text as vector outlines (`text_layer.outlined_pages`) has nothing in its text layer to check against. A value whose only failed check is grounding is **unverified** with reason `outlined_text`, not Low. (b) `column_bands` matches headings of several words ("INV DATE", "CHECK #"). A value lying wholly between its neighbouring columns' headings counts as under its own column. (c) a quote that dropped the printed spaces grounds when its characters match the page with the spaces removed: 8 or more characters, ending on a token boundary. (d) a row's record includes up to 3 lines above it on the same page, but never a line another row was read from |
| Q5 blank | 2cf8a3f | a label-only quote is not evidence of a missed value. A form with every slot blank is READY with "This form is blank". Parity between job 81 (alone) and job 83 (combined) is reproduced and fixed |
| Q9 missing-silent | 312adbb (N7), eb3430d | form-metadata widgets never create attention. A total or summary label whose own line prints a figure is evidence for that slot even when an equal figure is placed elsewhere (job 58: "Total liabilities and owners' equity 13,060" next to "Total assets 13,060") |
| Q12 no fail reason | 5e053fd; guard added in Q4 | every failure stores and shows a reason. A blank fillable form (≥10 widgets, none filled, no amount) needs no model call. **Found in Q4:** that shortcut would have answered the ADP W-2 (job 82) as blank without asking the model, because its values are outlines the text layer cannot see. Pages with outlined text now never take the shortcut |
| UI1 | 874a0af | "New extraction" runs a finished job's files again as a NEW job. The grid uses the job's own template |
| UI2 | 367bc79 | toasts sit bottom-right for 3 s and never cover an action. "Reviewed" shows inline |
| Q15 | d638e2f | `tools/audit_exports.py`, read-only, with the before numbers above |

### Found by the Phase 1 full suite (fixed in the Q4 commit)

- The Q9 own-line rule fired on `flowparse_card_us` ("Purchases $2,146.88"
  for "Total Purchases Listed"). The rule now applies only when the line
  itself prints the total word.
- At first, multi-word heading matching took `UNIT` away from a `Unit`
  column printed only inside `UNIT PRICE (£)`, which silently stopped the
  E10 check. A one-word heading may now reuse that word. "Between
  neighbours" never passes a value that overlaps, or sits flush with,
  another column's band.
- `arithmetic_validators.line_product` (Q3) raised `InvalidOperation` on a
  product with no cent representation, which broke the "validators never
  raise" property. Such a row is now skipped.

## Rules chosen

- **Side-by-side records are counted from the page's own heading.** A
  grouped record that the sheet lacks gets a visible flag, not a silent
  short table (the stricter choice). The flag names the page's count and
  the missing records. Its amount is the record's identity, so a record
  whose amount sits in any row counts as present.
- **Daily balances are left out of a transaction table** (any table with a
  withdrawal, debit, deposit, credit, description or check heading), and a
  note says so. They are not given a block of their own. A template that
  has its own balance table keeps them.
- **A row printed under another account number is flagged and Low.** It is
  never moved or dropped. The statement's own account is the account number
  printed most often.
- **Outlined text is "not checked", not "checked and failed".** A page
  counts as outlined when it has at least 300 glyph-sized paths and more
  paths than text characters. In the local corpus (253 pages) the ADP W-2
  measures 1.58 paths per character, the next page 0.46, and every other
  page under 0.07. Only a value whose sole failure is grounding moves to
  unverified; any other failed check still makes it Low.
- **A narrow heading:** a value lying wholly between the neighbouring
  headings (2 pt tolerance) is in its own column, even when it is closer to
  the next heading. A value reaching into a neighbour's heading still fails,
  so a date written to P.O. is still flagged.
- **A spaceless quote** grounds only from 8 characters and only on token
  boundaries, so `Purch.Doc.2235` does not ground a truncated `22356099`.
- **The record above a row** reaches at most 3 lines up, on the same page,
  and stops at another row's line, so a row cannot borrow its neighbour's
  vendor ID (tested).
- **Q9:** only total or summary labels (total, subtotal, net pay/income,
  grand, balance, YTD, average) step over their own caption words and
  accept a whole comma figure. Ordinary labels behave as before (tested).

## Not verified

- **No live model run.** Every Phase 1 reproduction uses a reconstructed
  answer, built from the export cells and quotes. `local_docs/raw` does not
  exist, so none of the `_real` twins that need a stored answer ran (they
  skip). The `_real` tests that read only the source PDF did run: carson
  group counts and the ADP W-2 outlined page.
- **Q2:** whether the model actually reads all three groups once told to has
  not been checked live. What is guaranteed is the flag when it does not.
  "Number of Checks 8" is reached by counting groups (3 + 5); the printed
  sentence itself is not parsed. The spec says 21 daily balances; the page
  prints 20.
- **Q4 (b) and (d)** were re-judged on a reconstruction of job 72 (export
  headers and quotes through the real pipeline). Placement flags went from
  5 to 0 and grounding misses from 30 to 20. The remaining 20 come from the
  export's own reformatting (`75` for `75.00`, dates as datetimes), not from
  the engine. Job 73's 87 placement cells were not reconstructed.
- **Q4 (e)–(g)** (jobs 78, 79, 62) were not worked on separately. The
  re-score below shows job 78 and job 79 unchanged.
- **Q9:** job 62 stub 1 (four totals and Regular YTD) and job 56
  Interest/Average have no test of their own. They are covered only by the
  general total-label rule.
- **UI1/UI2:** this session changed nothing in the frontend, so the
  frontend tests, type-check and build were not re-run here.

## Low cells before and after (real exports, offline)

A scratch re-score (not committed) took every cell in the 42 real exports
whose comment starts "NEEDS REVIEW — Low". Where the only reason was "Not
found on the page as quoted", it re-checked the cell with the current
`verify_span` against the source PDF and with `outlined_pages`.
**Placement Lows cannot be re-judged from an export**: the row's geometry
is not in it. They were counted as still Low, so this is a lower bound on
the improvement.

| | Low cells |
|---|---:|
| before (staging exports) | 601 |
| after (Run Q Phase 1 rules) | 528 |

| export | before | after |
|---|---:|---:|
| job 72 | 114 | 82 |
| job 82 (ADP W-2) | 19 | 0 (unverified, `outlined_text`) |
| job 83 | 20 | 1 |
| job 84 | 104 | 103 |
| job 73 | 93 | 92 |
| job 48 | 5 | 4 |
| job 60 | 139 | 139 |
| job 67 | 40 | 40 |

(The audit tool's 782 "low" counts red-filled cells. 601 counts cells whose
comment says Low. The re-score uses the comment, because the comment is
where the quote is.)


## Phase 1 final checks

| check | result |
|---|---|
| backend suite | 5408 passed, 19 xfailed, 0 failed |
| harness templated / no-template | 98.7% / 98.2%, 17/17 both, invented 0, misfiled 0 |
| frozen scoreboard (acceptance, jobs 15/19/21/25) | passes inside the suite |
| frontend | not re-run: no frontend change in this session |
