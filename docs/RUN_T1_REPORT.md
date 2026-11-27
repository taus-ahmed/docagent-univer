# Run T1 report — engine foundation and structure engine core (fix/review-fixes)

Rules kept: tests first; no live model call (every answer mocked or replayed);
`.env` never read; no deploy; frontend untouched; literal scan
(`tests/test_engine_generality.py`) green after every engine commit. Organized
stays behind `?layout=organized`; `NO_TEMPLATE_USES_STRUCTURE` and
`STRUCTURE_PLANS_AT_EXTRACTION` default off.

## Items

| # | cause | change | tests | commit |
|---|---|---|---|---|
| 1a | an answer over the output limit was asked again unchanged (8-page list: MAX_TOKENS at 21,334 output tokens, then "no parseable response") | `engine/call_sizing.py`: estimate before the call (lines printing a date or amount × (60 + 20/column) + 80/field); under 60% of the model's limit one call, else page groups sized to the budget; MAX_TOKENS / timeout / unparseable / a 400 whose cause is size → halve to one page, then split by row ranges at row boundaries; later pieces carry heading line + group header as context never returned as rows; merged in page order, seam repeats kept once; a piece failing at the smallest size names its pages (attention), the rest kept; `[SIZING]` log + `diagnostics.call_strategy`. A 400 for any other cause is still not retried smaller (pins `test_r4_failed_call`). A replay of stored answers replays the recorded call plan (`RECORDED_PLAN`) | `test_t1_call_sizing.py` (22): MAX_TOKENS, timeout, 400, unparseable, cross-page table, group header carry, 8 pages / 400 rows, row split, refusal not split | 756db9e, 81e988d |
| 1b | job summary used one blended $0.15/1M (a $0.0569 call showed $0.0083) | `llm_contract.cost_breakdown`: per model, input/output apart, thinking as output, every attempt (inference, retries, pieces, options, structure plans); `JOB COST` log line with per-model split; blended rate only when no counters, said so | `test_t1_cost.py` (11) with known token counts | b4cc6fb |
| 1c | — | >28-field schema rule and 400 logging kept; a refused request recovers at document level (schema 400 → answered without schema; size 400 → sized; other 400 → fails with its reason) | `test_t1_refused_recovers.py` (3), real GeminiClient mocked at urllib | 176f629 |
| 2a | the Organized reader had boxes/fonts but no colour, rotation or quality | `engine/perception.py`: words with box, font, bold/italic, size, colour, rotation (non-upright text grouped by run); per-page quality score (garbled glyphs, vowel-less runs, outlined text, image regions) choosing text layer or OCR, naming OCR regions; double-struck text read once | `test_t1_perception.py` | 182a87a, 1da5f62 |
| 2b | punctuation between words, a description wrapped past its row's figures, and `26.08 -` gave false Lows | `normalise`, `loose_key/loose_find`, `trailing_minus`; `verify_span` ignores punctuation between words (token-bounded, 4+/8+), lets a text value skip only FIGURE tokens inside its own span/record, lets a negative value ground on a figure followed by a lone hyphen | perception + Batch 4 shapes | 8a0fc11, 03522c3 |
| 2c | — | lines by baseline (tolerance ⅓ body size), superscripts kept on their line, stacked two-line cells (x-overlap, gap under half the page's usual gap) | `TestLines` | 182a87a |
| 2d | the old watermark rule removed on ONE signal | background removed only on two signals (rotated+large, faint, repeated at one position across pages, behind content), never on a label/value or table line, never part of a line; pale text on a dark fill is not faint; side panels split by a wide alley before lines are formed; removed words kept with reasons | diagonal SAMPLE/DRAFT/CONFIDENTIAL removed; rotated headers and vertical side text kept | 182a87a, 523fae0 |
| 2e | — | widget values and checkbox states (`[X]`/`[ ]`) as positioned words | real fillable fixture | 182a87a |
| 2f | staging wipes uploads at every deploy | `document_results.perception_json` (boot DDL, `ADD COLUMN IF NOT EXISTS`), packed words + lines of the record's pages, read once per file | `test_t1_perception_store.py` | 00dea37 |
| 3a–3c | Organized made every distinct left edge on the page a sheet column | `engine/structure_engine.py`: plan schema; request = numbered lines with coordinates + the geometry's proposal, plan only, temperature 0, per page, long pages in line-range pieces through 1a; validator (ids, overlaps, every line assigned or ignored with a reason, and **owner addition**: a table boundary the geometry does not propose is invalid unless the plan names the contradiction, then accepted and flagged); invalid → one retry with the errors named → fallback | `test_t1_structure.py` | ed6f90a |
| 3d | — | `engine/structure_geometry.py`: candidate rows, blocks, column boundaries from alleys ≥ gutter (narrower only where a heading starts) and shared right edges; heading over no data keeps its column; fallback plan (title, label/value, table with stacked heading / repeated groups / group lines / continued headless pages, note, side panel, furniture); notes never take a line with a date, widget, `Label:` pair or gutter split | synthetic + `TestNotNote`, `TestNoDataColumns` | 5c3939a, 245da11, 789dfb4, 00ef2f2 |
| 3e | — | compact grid per region from column A, regions one blank row apart, header once per table, label WITH colon and value beside, group id as text, wrapped lines joined, `organized_layout.typed` (one date format, money decimals, trailing minus `#,##0.00;#,##0.00-`, identifiers as text), `= + - @` text stored as text, cell length limit, underline/thick rules, no fills | `TestCompactGrids` | ed6f90a |
| 3f | — | every kept word placed exactly once; excluded lines listed with reason; plan-vs-geometry column/membership disagreement named; running-balance breaks named; two figures in one cell named; nothing changed or marked Low | `TestVerify` | ed6f90a |
| 3g | — | plans keyed sha256(file + model + prompt version + plan version + page), stored on the perception; same input → same layout | `TestDeterminism` | ed6f90a |
| 3h | — | `?layout=organized` = structure layout from STORED words (file only for older records), stored model plan or geometry, `Layout check` sheet (plan per page, flags, left-out lines); export never calls the model; the two switches in config + OPERATIONS.md | `tests/http/test_t1_structure_route.py` (6) | 06337b2 |
| 4 | — | `tools/make_synthetic_layouts.py` (15 cases, 5 vocabularies, ground truth), `tools/structure_metrics.py` | `test_t1_synthetic_layouts.py` (19) | 3f69ed0 |

**Test changed (owner decision):** `tests/http/test_organized_export_route.py`
expected the colon-stripped `Employer Name`; it now expects `Employer Name:`.
**Replays:** `tools/replay_raw.py` and the job-138 test's scripted replay
set `RECORDED_PLAN`; their assertions are unchanged.

## Metrics, both halves (`local_docs/corpus_metrics/structure_metrics.json`, `rt1b.md`)

Organized: old layout vs structure engine (geometry plan, no model), same
instrument (`tools/run_t_metrics.organized`).

| metric | dev old → new | report old → new |
|---|---:|---:|
| documents laid out | 35 → 35 | 25 → 25 |
| widest-page columns, summed | 311 → 193 | 212 → 145 |
| empty sheet columns | 7 → 0 | 8 → 0 |
| printed figures not placed | 0 → 0 | 0 → 0 |
| lost leading zeros | 0 → 0 | 0 → 0 |
| tail lines as rows | 10 → 9 | 10 → 11 |
| glued cells (2+ figures) | 33 → **116** | 127 → 61 |
| column-order errors (noisy, see Run T) | 229 → 124 | 252 → **387** |

Synthetic set (ground truth): right column 91.6% → 100%, coverage 97.1% →
100%, row order 93.2% → 100%, background in a cell 7 → 0. **This set was
built alongside the engine; it shows the failure classes are handled, not
an independent accuracy.**

Read with care: the report half's column-order rise is concentrated in
`long_digital_25pg` (199 → 291) and `unm_paystub` (2 → 58); dev's glued rise
in `boa_how_to_read` (an explainer, 14 → ~83 after the double-strike fix)
and date ranges the instrument counts as two figures. Not tuned on: per the
rule, report-half documents were measured, not fixed.

Regular export (replayed stored answers, `corpus_metrics --tag rt1b
--compare t2`): unchanged except 3 dev no-template cells Low → amber; false
Lows 300 → 300, wrong at high 20 → 20.

**Batch 4** (`local_docs/batch4/Batch 4`, jobs 140–153 now present). Carson
(142 templated, 144 no-template): the frozen exports' "not found as quoted"
Lows re-grounded against the PDF: 142: 37/51 before T1 → **48/51**; 144:
9/18 → **14/18** (left: a quote from another line; `0` written for `0.00`).
"Sits under a different column" Lows (29, 55) are untouched by T1. Oregon
(150): the template's `Line/Description/Quantity/Unit Price/Tax Rate/Line
Amount` band replaced the page's five budget columns; the structure layout
keeps `Budget Category | Budget Amount | Previously Invoiced | Current
Invoice | Cumulative Total`.

## Checks

| check | result |
|---|---|
| harness templated (replay) | 98.7%, 17/17, invented 0, misfiled 0, defect 0.0% |
| harness no-template (replay) | **not run**: `CacheMiss` on EXP-2024-0081 inference — reproduces at dc67e84 (before T1) in a clean worktree; needs a live re-record (not allowed) |
| full suite (final, 81e988d) | **5904 passed, 0 failed**, 19 xfailed (the run before it found 4 real-data replay failures, fixed in 81e988d) |
| literal scan | green |

## Not verified

* No live model call: the sized pieces, the structure plan request and its
  retry are proven only against scripted answers; the vendor list's real
  sized run is unmeasured (on replay it has no stored answers for the new
  calls).
* No real client documents beyond the corpus and Batch 4's frozen exports.
* OCR is not connected to the structure layout: a page the quality score
  sends to OCR is skipped with a reason.
* Model plans are off by default; every corpus number above is the geometry
  plan.
* Stage gates: Stage 1's own suite run was contaminated by concurrent edits
  and stopped; Stages 1–2 and 3–4 were gated together (progress log).

## Open items for Part 2

1. Report half: column-order errors on `long_digital_25pg`, `unm_paystub`
   (measure the cause before any change; develop on dev).
2. Glued cells on explainer pages (dev `boa_how_to_read`): multi-column
   prose zones read as one line.
3. Stacked headings with two-line records (sub-field columns) — the
   fallback joins the headings into one label; records two lines tall are
   not split into sub-columns.
4. Chart detection (vector graphics) — only side zones by alley today.
5. Connect OCR word boxes to perception (`ocr_source`) so scans lay out.
6. A live run: vendor list sized extraction, structure plans on 5 corpus
   documents, cost per job against the provider's bill.
7. Re-record the no-template harness cache (EXP-2024-0081) on a machine
   allowed to make live calls.
8. Owner approval before `NO_TEMPLATE_USES_STRUCTURE` is turned on.
