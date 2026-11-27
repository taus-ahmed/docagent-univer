# RUN T1 PROGRESS — engine foundation and structure engine core

Branch `fix/review-fixes`. No deploy. No frontend. Resume from the first
unchecked item. "RUN T1 DONE" goes on line 1 only when every stage is done.

Baseline (before T1): _to be filled in at Stage 0_.

## Stage 0 — read and baseline
- [ ] read HOW_DOCAGENT_WORKS, RUN_T_REPORT, ENGINE_ARCHITECTURE_V2, ORGANIZED_LAYOUT_SPEC, KNOWN_FAILING
- [ ] baseline: full suite, harness both modes, corpus split (dev half / report half)

## Stage 1 — model-call sizing and cost
- [ ] 1a adaptive chunking (estimate, whole-vs-split, halve on MAX_TOKENS/timeout/400/unparseable, row-range split, carried state, merge/dedupe, visible failed-pages reason, strategy log)
- [ ] 1b cost accounting (per-model input/output rates from one table; retries, chunks, thinking; job summary + logs)
- [ ] 1c schema-size rule kept (>28 fields: no response schema), 400 logging, refused request recovers
- [ ] stage 1 full suite + harness + push

## Stage 2 — perception (code only)
- [ ] 2a words with box/font/size/colour/rotation; per-page text-layer quality score
- [ ] 2b normalisation (dashes, NBSP, ligatures, glued/split tokens, trailing-minus sign token)
- [ ] 2c lines by baseline; two-line stacked cells; superscripts
- [ ] 2d background suppression (>=2 signals; removed list with reasons; keep rotated headers/side text)
- [ ] 2e form field values / checkbox states as positioned words
- [ ] 2f words + lines stored as JSON per document in the database
- [ ] stage 2 full suite + harness + push

## Stage 3 — structure engine core (behind the flag)
- [ ] 3a plan schema
- [ ] 3b request (image + numbered lines; plan only; temp 0; per page; Stage 1 split)
- [ ] 3c validator + one retry + fallback
- [ ] 3d deterministic fallback layout
- [ ] 3e placement (compact grids, formats, types, formula-safe text, Excel limits)
- [ ] 3f verification independent of the plan
- [ ] 3g determinism (plan cache by file hash + model + prompt version; plan version)
- [ ] 3h wire to ?layout=organized and NO_TEMPLATE_USES_STRUCTURE, with reason codes
- [ ] stage 3 full suite + harness + push

## Stage 4 — synthetic failure-class tests and metrics
- [ ] tools/make_synthetic_layouts.py with ground-truth grids
- [ ] metrics old vs new on both corpus halves + synthetic set
- [ ] Batch 4 re-measure (only if local_docs/batch4 exists)
- [ ] stage 4 full suite + harness + push

## Stage 5 — report
- [ ] docs/RUN_T1_REPORT.md
- [ ] final push

## Log
