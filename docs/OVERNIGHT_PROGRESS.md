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
- [x] D3 — T9 ambiguity text says what the prompt carries: Item / Debit / Credit
- [x] GATE D — pytest exit 0: 5235 tests, 0 failures, 0 errors (18 skipped incl. xfails, down from 21); harness 98.7 / 98.2, 17/17, defects 0; scoreboard silent 0, false flags 0
- [x] E1 — lib/reviewRefresh.ts: every review action invalidates review, job-results, job and jobs; the Extract page reads results through the job-results query; frontend test + API test (edit and correct-and-accept persist in GET /results and the Excel)
- [x] E2 — review lists every page of the document (ledger / inventory), page endpoint returns page_count, dialog has Previous / "Page n of N" / Next and the value list follows the page; frontend + API tests; manual check section F
- [x] GATE E — pytest exit 0: 5241 tests, 0 failures, 0 errors; harness 98.7 / 98.2, 17/17, defects 0; scoreboard silent 0, false flags 0; frontend type-check, 72/72 tests, build OK
- [x] M1 — CANDIDATES (incl. gemini-flash-latest / -lite-latest) removed; GEMINI_MODEL_FALLBACKS (default empty); a 404 fails naming the model and saying none was substituted
- [x] M2 — job_worker.model_of stores the API's modelVersion (fallback: requested name); Legend says "Extracted by: <model>"; History job detail shows a Model badge
- [x] M3 — docs/MODEL_MIGRATION.md (facts from Google's pages, 2026-11-20, unverified live); gemini_client.MODEL_PROFILES + GEMINI_MODEL_PROFILES (2.5 request unchanged, 3.x: no temperature, thinkingLevel); 3.x prices; live_cap env-configurable, never removable; tools/model_matrix.py written, NOT run
- [x] H1 — audit_events table (append-only via ORM listeners), core/audit.py (route hooks + middleware for templates, jobs, exports, review), GET /api/admin/audit (admin-only, paged, filtered, firm-scoped; in the all-routes isolation suite), /admin/audit page
- [x] H2 — users.token_version ("tv" in every token, checked on every request); password change / self-set / admin reset, disable, delete, firm deactivation and POST /api/auth/logout-everywhere bump it; change-password returns this device's new token; "Sign out everywhere" button
- [x] H3 — core/password_policy.py (12+, not the username, not a common password or plain sequence) on create, admin reset, PUT /me, change-password and bootstrap; plain messages that never echo the password
- [ ] H4 — raw response retention + log redaction
- [ ] RUN-G — merge origin/review/run-g before the final run; tests/test_batch1_real_defects.py (10 strict xfails) must pass, each marker removed when its fix lands
- [ ] FINISH — final checks, KNOWN_FAILING, TEMPLATE_RULES, OVERNIGHT_REPORT, push
