# Overnight run — progress (branch fix/review-fixes, started at cd2dbd4)

A restarted session reads this first and skips every item marked [x] or BLOCKED.

- [x] CI1 — CI-only failures: git-ignored local_docs PDFs skip on CI with the file named; checkout fetch-depth 0 for `git show 56e80ca`; -ra --durations=20 (1f8e7a0)
- [x] A1 — wrong-slot and duplicate values: engine/ownership.py (box owner by geometry, checkbox X by x-position, unwitnessed duplicate cleared); completeness box-caption rule
- [x] A2 — a row printed in another box never enters a box-coded band; Box 14 second entry flagged in plain words
- [x] A3 — identifiers (name/locality/control) text; years plain; money labels always 2 decimals; Box d trimmed to its own box; printed space recovered from char gaps; ID slots not demoted as phone numbers
- [x] A4 — recover_lost_pages: one page-targeted call per lost page (PAGE_RECOVERY_MAX_CALLS, default 4), merged in page order; a column header reprinted at the top of the next page is a continuation
- [x] A5 — one printed form title fills an empty Form Type (machine_read form_title); several are an empty-flagged slot naming them
- [x] A6 — parity test (alone vs combined: same record, same block); one-entity fragment rows merged; EXTRACTION_TEMPERATURE=0 on every extraction call, recorded per attempt (suite and replay pin 0.1 = the cache recording)
- [x] GATE A — pytest exit 0: 5188 tests, 0 failures, 0 errors (junit); harness 98.7 / 98.2, 17/17, defects 0; replay scoreboard silent 0, false flags 0; frontend type-check, 64/64 tests, build OK
- [x] B1 — dot leaders no longer hide a number; a glued-line quote yields to the value the page spells; a label-row quote grounds the value beneath its own heading (alias-matched). A quote found with the value not in it stays Low (protected)
- [x] B2 — placement also accepts a value aligned with its own column's values (set_column_anchors: modal left/right edge of >= 3 values that overlap the heading); a description written into Date still fires; McGuire case pinned (not reproducible on current code)
- [x] B3 — fillable form: empty widget = confirmed empty (no reason, no second request; tables confirmed when every filled figure is in a cell); text layer: a printed label counts only with its whole caption and a value-like token after it
- [x] B4 — slot writer marks EVERY slot, so an empty-and-flagged slot is the grey cell with a comment the Legend counts; tests/legend_check.py (real exports before: 3 of 16 disagree — jobs 46, 48, 51)
- [x] GATE B — pytest exit 0: 5213 tests, 0 failures, 0 errors (junit); harness 98.7 / 98.2, 17/17, defects 0; scoreboard silent 0, false flags 0; frontend unchanged since GATE A (type-check, 64/64, build OK there)
- [x] C — merged origin/review/run-f; all 13 strict xfails fixed and their markers removed (F2 x3, F4 x4, F5, E9 x2, E11, E12 x2); _on_page refuses a value assembled across columns
- [x] GATE C — pytest exit 0: 5235 tests, 0 failures, 0 errors (junit); harness 98.7 / 98.2, 17/17, defects 0; scoreboard silent 0, false flags 0; frontend unchanged
- [x] D1 — period cue (years, Q1-Q4, FY, H1/H2, months) for matrix headings; a total word makes a field only as a short label (<= 3 words); two runs a blank column apart are two tables when each names money or a later row labels both; 3 markers off
- [x] D2 — the D13 inventory test asserts F10's two formula warnings by grid and text
- [ ] D3 — stale T9 ambiguity text
- [ ] GATE D
- [ ] E1 — review edits revert (owner note: API persists; stale frontend state — ReviewPanel does not update result.extracted_data, ResultsGrid.refresh() invalidates only the review query; refetch/invalidate the results query after EVERY review action, status and added rows too; frontend test)
- [ ] E2 — multi-page navigation in the review dialog
- [ ] GATE E
- [ ] M1 — no -latest candidates; GEMINI_MODEL_FALLBACKS; 404 fails visibly
- [ ] M2 — store modelVersion in model_used; Legend + job detail
- [ ] M3 — migration doc, per-model settings, tools/model_matrix.py
- [ ] H1 — audit log
- [ ] H2 — token revocation
- [ ] H3 — password policy
- [ ] H4 — raw response retention + log redaction
- [ ] RUN-G — merge origin/review/run-g before the final run; tests/test_batch1_real_defects.py (10 strict xfails) must pass, each marker removed when its fix lands
- [ ] FINISH — final checks, KNOWN_FAILING, TEMPLATE_RULES, OVERNIGHT_REPORT, push
