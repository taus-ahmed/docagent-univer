# RUN T2 PROGRESS — checker, structure fixes, forms, OCR, reviewer edits

Branch `fix/review-fixes`. No push to main, no deploy, no frontend.
`NO_TEMPLATE_USES_STRUCTURE` and `STRUCTURE_PLANS_AT_EXTRACTION` stay OFF.
No live model call. Resume from the first unchecked item.

## Stage 1 — a checker we can trust
- [x] `tools/position_check.py` — positional checker against an answer key (text, header, row label)
- [x] `tools/draft_answer_key.py` — draft from pdfplumber words (not the engine); keys corrected by hand
- [x] 11 keys in `tests/fixtures/answer_keys/` (dev 6, held-out 5)
- [x] `tests/test_t2_position_check.py` — one failure class per test
- [x] baseline old vs new, both halves; 10 failing cells per half with page text
      (`local_docs/corpus_metrics/t2_check_baseline.{txt,json}`; re-scored at 1eff903 after the key fixes)
- [x] stage 1 full suite (gate at 1eff903: green, see log) + commit (f434f0e, 1eff903)

## Stage 2 — fix what the checker proves wrong
- [x] regressions: long_digital_25pg, unm_paystub, boa_how_to_read
- [x] glue: date+description, invoice line items, ACHDEBIT-style, bold on values, section title as row label, Total value under wrong column
- [x] stage 2 full suite (gate at 5599ca7: green, see log) + commit (5599ca7)

## Stage 3 — form values
- [ ] AcroForm widgets (name, rect, value) to the label of the box holding them; split labels merged; several forms = several regions; `$` with its value
- [ ] stage 3 full suite + commit

## Stage 4 — OCR
- [ ] Tesseract pinned (Docker, CI), version in job log; OCR words in perception format with per-page trust; same plan/placement/verify path; 3 scanned samples
- [ ] stage 4 full suite + commit

## Stage 5 — stacked headers, wrapped tables, charts
- [ ] stacked headers; repeated column groups one table; side-by-side blocks; instruction/bullet text excluded with reason; charts excluded
- [ ] stage 5 full suite + commit

## Stage 6 — reviewer structure edits (backend)
- [ ] endpoints, stored plan edits (who/when), export applies them, deterministic; docs/REVIEWER_STRUCTURE_API.md
- [ ] stage 6 full suite + commit

## Stage 7 — live run tool (not run)
- [ ] tools/live_structure_check.py ($1 cap, per-call log), PowerShell commands, vendor list + expense report, 20-doc comparison set
- [ ] stage 7 full suite + commit

## Stage 8 — report
- [ ] docs/RUN_T2_REPORT.md

## Split (Stage 1)

The 11 documents are split BY HAND, not by the corpus hash, so that the
documents Stage 2 is told to fix are in dev (tuning on them is allowed) and
the held-out half is never worked on:

| dev (tuned on) | held-out (measured only) |
|---|---|
| mammoth_2pg, flowparse_invoice_tax, utah_paystub_2, long_digital_25pg, unm_paystub, boa_how_to_read | carson_bank_6pg, flowparse_bank_us, flowparse_cafe, irs6744_w2_mcguire, irs6744_1099NEC_1099K_garcia |

* long_digital_25pg's pages 1–6 ARE carson_bank_6pg; its key covers only
  pages 8, 12 and 26 so dev never sees a held-out page.
* Stage 3 (forms) is developed on `irs_1099nec_ellis` (AcroForm, not keyed)
  and tested on the two held-out IRS keys, as the brief asks.
* Stage 5's carson daily-balance case is held-out: repeated column groups
  are developed on long_digital's card page and synthetic cases, and
  carson is measured.

## Log
- f434f0e: checker, draft tool, 11 keys, checker tests (14).
- Stage 1 gate #1 (worktree at f434f0e): 57 failed / 5778 passed — INVALID: every failure is
  "required local corpus file is missing"; the `local_docs` junction into the gate worktree
  had not been created (quoting in the gate script). Fixed; the script now refuses to run
  when the junction is missing and removes the junction before removing a worktree.
- 1eff903: checker refinements found while keying (unmarked heading rows, `group:` items,
  wrapped splits, wrong-row matching, old-layout page mapping) and long_digital key fixes
  (`Date Submitted` is the printed heading; vendor lines are group labels; report footer
  lines excluded).
- Stage 1 gate #2 at 1eff903: 5907 passed, 11 failed, 19 xfailed (54 min). All 11
  (test_batch2_failure_classes x10, test_run_f_fixes f1) read their PDFs from the folder
  BESIDE the repo (`..\docagent-testdocs`), which a gate worktree did not have. With that
  folder linked beside the worktrees, the two files re-run at 1eff903: 18 passed. Stage 1
  gate: 0 real failures.
- Baseline RE-SCORED at 1eff903 (corrected keys, Stage 1 engine) — the "before" for Stage 2:
  dev old 72.8% header / 96.4% row / 5 glued / 41 missing; dev new 77.8% / 84.5% / 16 / 42;
  held-out old 86.4% / 86.4% / 5 / 67; held-out new 83.5% / 85.9% / 2 / 45.
- 5599ca7 Stage 2. Causes found by the checker and fixed (all general, tested on synthetic
  pages in tests/test_t2_structure_fixes.py, 19 tests):
  * table start: the heading DIRECTLY above the rows (address block above a table was taken
    as the heading - invoice); table end at the next table's heading/title (unm: four printed
    tables were one region; utah: dates table swallowed the earnings table)
  * section lines (`Taxes`, `Gross Pay`) were glued onto the row above as tails
  * 3-line stacked headings; one-row tables; Label: total row aligned under its column
  * markup (red reviewer annotation) rule lost from Organized v1 - restored, never on a row
  * printed gap with no space char (ACHDEBIT, EmployerEmployer); touching glyphs ($ 3 2, o f);
    word+figure glue (Checks8); invisible OCR overlay fonts made every value bold
  * offset headings (Leave Type over Annual Leave) claim headless columns; narrow alley under a
    heading break is a column (John Q. Doe | 000000000); numeric columns by cell not word
  * range wrap (01/01/17 - / 01/31/17); wrapped kv values (rule 5); every Label: pair split
    (Account: … Period: …); in-cell word order by line ($ 9 6 read as "6 9 $")
  * reprinted heading written once only over a real continuation; Label: lines inside a table
    placed by pairs (CHECK DATE:); `n of m` page numbers inside a line are furniture
  Dev after: right header 95.0%, right row 99.7%, glued 1, split 2, missing 9.
  Held-out after (measured, not tuned): 82.0% / 81.5% / 8 glued / 59 missing. carson's right
  row fell 96.1% -> 90.1% and is NOT explained: carson is held-out and long_digital pages 1-6
  are the same pages, so neither was opened. An old-vs-new scan of the five UNKEYED corpus
  statements found no general regression (2-figure cells 18 -> 8, no new glue).
  Remaining dev failures: long_digital p8 card-type heading spanning two sub-columns
  (Stage 5), callout notes (Stage 5), boa's overlaid sample copies (extra cells).
- Stage 2 gate at 5599ca7: 5926 passed, 11 failed, 19 xfailed (48 min); the same 11
  sibling-folder failures as Stage 1 (the gate started before the folder was linked).
  Re-run at 5599ca7 with it linked: 18 passed. Stage 2 gate: 0 real failures.
- Baseline at f434f0e (first key version): dev old 69.3% header / 94.8% row / 7 glued;
  dev new 73.9% / 84.0% / 35 glued; held-out old 86.4% / 86.4% / 5; held-out new
  83.5% / 85.9% / 2.
