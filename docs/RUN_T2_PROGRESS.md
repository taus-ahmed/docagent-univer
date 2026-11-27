# RUN T2 PROGRESS — checker, structure fixes, forms, OCR, reviewer edits

Branch `fix/review-fixes`. No push to main, no deploy, no frontend.
`NO_TEMPLATE_USES_STRUCTURE` and `STRUCTURE_PLANS_AT_EXTRACTION` stay OFF.
No live model call. Resume from the first unchecked item.

## Stage 1 — a checker we can trust
- [x] `tools/position_check.py` — positional checker against an answer key (text, header, row label)
- [x] `tools/draft_answer_key.py` — draft from pdfplumber words (not the engine); keys corrected by hand
- [x] 11 keys in `tests/fixtures/answer_keys/` (dev 6, held-out 5)
- [x] `tests/test_t2_position_check.py` — one failure class per test
- [ ] baseline old vs new, both halves; 10 failing cells per half with page text
- [ ] stage 1 full suite + commit

## Stage 2 — fix what the checker proves wrong
- [ ] regressions: long_digital_25pg, unm_paystub, boa_how_to_read
- [ ] glue: date+description, invoice line items, ACHDEBIT-style, bold on values, section title as row label, Total value under wrong column
- [ ] stage 2 full suite + commit

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
