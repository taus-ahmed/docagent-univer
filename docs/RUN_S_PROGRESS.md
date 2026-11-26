# RUN S progress (engine overhaul) — IN PROGRESS

Branch `fix/review-fixes`. Resume from the first unchecked item.
Rules: test first; no test deleted/weakened/skipped; no live Gemini; never read .env;
one commit per item; push after each stage; UI untouched.

## Stage 0 — setup
- [x] Read RUN_R_REPORT, ORGANIZED_LAYOUT_SPEC, RUN_Q_PHASE2_FINDINGS
- [x] docs/ENGINE_ARCHITECTURE_V2.md (≤2 pages)
- [x] Corpus split (dev half / report half) + corpus metrics tool + baseline metrics
- [x] Generality test: engine code holds no literals from local test documents

## Stage 1 — conservation, group headers, dense pages
- [x] 1a coverage reconciliation ("printed but not extracted") on every document
- [x] 1b group headers: identifier + name as separate columns on every row
- [x] 1c dense / multi-form pages: targeted recovery before flagging
- [x] 1d synthetic PDFs in several vocabularies/layouts (group headers: vendor/customer code/employee/no-id; more with 1a)
- [x] 1e job 138 amber reasons ranked; false ones fixed
- [ ] Stage 1 finish: suite + harness + scoreboard, KNOWN_FAILING, push

## Stage 2 — organized layout for all text-layer PDFs
- [ ] 2a spec extension in ORGANIZED_LAYOUT_SPEC.md
- [ ] 2b position placement (x/y), jumbled-layout tests
- [ ] 2c headers (one per table, no invented "Description"), colon strip, no stray headers
- [ ] 2d formatting from page, blank rows by spacing, no paragraphs/fills, one date format
- [ ] 2e family tests (bank, invoice, PO, W-2, 1099, 1098, receipt, pay stub; utah_paystub_2 vs syed sample)
- [ ] Stage 2 finish: suite + harness + scoreboard, KNOWN_FAILING, push

## Stage 3 — known defects (general rules)
- [ ] 3a grounded value whose meaning mismatches the label (ENGIE Customer Email)
- [ ] 3b wrong-template warning, jobs 61 and 65
- [ ] 3c job 62 two-column fields
- [ ] 3d job 79 Box 4
- [ ] 3e no-template RAW 59.4% vs 70.1%: bisect and explain
- [ ] 3f Legend counts vs marked cells (jobs 46, 48, 51)
- [ ] 3g job 130 smartsheet_mileage finished with no values
- [ ] Stage 3 finish: suite + harness + scoreboard, KNOWN_FAILING, push

## Stage 4 — image / OCR word-box path, watermarks
- [ ] 4-gen tools/make_synthetic_checks.py (≥40 checks, PDF + image, ground truth JSON) → local_docs/synthetic_checks/
- [ ] 4-before per-field accuracy baseline by watermark strength
- [ ] 4a one OCR word-box path into the same placement/verification engine
- [ ] 4b watermark/background suppression chosen by measured accuracy
- [ ] 4c MICR line reading as its own check
- [ ] 4d OCR vs model disagreement flagged; amount figures vs words reconciled
- [ ] 4e after report by watermark strength; checks_specimens if present; ou_check_stub, saltlake_paycheck, receipt photos retried
- [ ] Stage 4 finish: suite + harness + scoreboard, KNOWN_FAILING, push

## Finish
- [ ] docs/RUN_S_REPORT.md (per item cause/change/tests/not fixed; both corpus halves before/after; not verified)
- [ ] "RUN S DONE" on line 1

## Log

- Stage 0 done: de2a7a5 generality test, 29670b2 architecture, 1ec9ffd corpus tool.
- Job 138 is NOT in local_docs/raw (stops at 134). Job 131 (same file, mobile_vendor_list_8pg) stands in;
  138's defect (model answered the group column with names only) is reproduced synthetically.
- Baseline `local_docs/corpus_metrics/before.md` (HEAD 5ecb820 code, 93 docs, 5 skipped: no stored answer):
  all: tokens 5273, coverage 66.5%, silent 1240, amounts missing 689/2174, silent blanks 20, low 923, amber 790,
  key right 2098 / wrong 5, false low 370, wrong high 2. dev 61 docs, report 32 docs.
- 1b done 5c07443 (split group id/name, page wins, inferred header amber). R1 contract tests updated to the split.
- 1a done 9c43d77 (engine/conservation.py; gold replay accuracy unchanged 98.7%; tools/gold_attention.py).
- 1e done e0ff352: job 138 export found in owner's Downloads, copied to local_docs/batch4/. All 686 marks = one
  reason "Low: Not found on the page as quoted"; cause = group-column (vendor name) checked against the row's own
  line. Fixed; reconstruction from job 131's rows: 59 Low rows -> 0.
- 1c done 52b5ec5 (dense-page recovery trigger from conservation; request names the lost lines).
  Multi-form pages: not recoverable into a template that lacks the form; conservation names the figures.
- NEXT (resume here): tests/test_s1a_conservation_real.py is WRITTEN, NOT YET RUN OR COMMITTED (named cases
  127/95/115/129/131). Run it, fix, commit. Then Stage 1 finish: full suite once, both harness modes,
  scoreboard, corpus_metrics --tag s1 --compare before, KNOWN_FAILING, push.
  (Corpus tag s1a ran on code before the bottom-band rule was removed; rerun as tag s1.)
- 3e finding (read-only, history of tests/reports/latest-notemplate.md): no-template RAW 70.1% at fd5a142 ->
  58.4% at 800d540 (I5: inference reads column_text) -> 59.4% at e20e844 (Run A). The whole first drop is
  EXP-2024-0081 raw 98.1% -> 13.0% (headline 98.1% unchanged: adapter widenings recover the renamed schema);
  +1.0 from BS-2024-Q1 54.3->58.7 and PAYSLIP-0007 89.2->94.6. CLAUDE.md's 70.1% predates 800d540.
- 3b finding: jobs 61/65 (utah_paystub_1 under a PO template) get no wrong-template warning: hint scores
  payslip 1, tax_form 1, purchase_order 0; type_mismatch needs >=2 hits for another type. Plan: template's own
  labels printed fraction as a second signal.
