# Run R progress — fix/review-fixes

Read this first on a restart; skip items marked done.

## Part 1: Batch 3 defects
- [x] R1 job 131: vendor column + 14 subtotal rows (engine/row_groups.py), grand total reconciled; 31/31 vendors on replay
- [ ] R2 job 95 carson_bank: missing printed amounts found, fixed or named
- [ ] R3 job 115 irs6744 1099-K: uncaptured amounts note visible in Results + Legend
- [ ] R4 job 133 fiserv failure cause + reason shown; job 129 fidelity investigated
- [ ] R5 UI "Template used: No template" for a templated job
- [ ] R6 CI: local_docs skip guards audit; OCR test machine-independent; xfail count 22 vs 20

## Part 2: Organized layout (option, default OFF)
- [ ] (a) docs/ORGANIZED_LAYOUT_SPEC.md
- [ ] (b) v1 for text-layer pay stubs + tests vs syed sheet (utah_paystub_2)
- [ ] (c) outputs in local_docs/organized_out/ + before/after note

## Finish
- [ ] full backend suite, frontend tests/build, harness, scoreboard (once)
- [ ] tests/KNOWN_FAILING.md
- [ ] docs/RUN_R_REPORT.md
- [ ] push fix/review-fixes, RUN R DONE
