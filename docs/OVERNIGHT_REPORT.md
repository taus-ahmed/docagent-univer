# Overnight run report — fix/review-fixes (from cd2dbd4)

Every item, what caused it, what changed, which tests prove it, and what is
not fixed. Every reproduction was written first from the real fixtures
(`local_docs/DocAgent_testdocs`, the 16 staging exports in
`local_docs/batch1_exports`) with scripted model answers copied from the
exports' cell comments; no live model call was made, no key read, no `.env`
opened, no dependency added.

## Before → after

| measure | before (cd2dbd4) | after |
|---|---|---|
| CI `ci/backend` "Backend tests" | 13 failed on every branch | the 13 causes fixed (CI not re-run here) |
| backend suite (local, junit) | 5,119 passed (CI log count) | 5,257 passed, 19 xfailed, 0 failed, 0 errors |
| harness, templated / no-template | 98.7% / 98.2%, 17/17 | 98.7% / 98.2%, 17/17, defects 0 (every group) |
| frozen replay scoreboard | silent 0, false flags 0 | silent 0, false flags 0 (every group) |
| frontend tests | 64 | 73 of 73 (type-check and build clean) |
| strict xfails, Run F review | 13 | 0 |
| strict xfails, Run E review | 3 | 0 |
| strict xfails, batch 1 (Run G) | 10 | 1 (item 9, BLOCKED — below) |
| real exports whose Legend disagrees with the sheet (`tests.legend_check`) | 3 of 16 (jobs 46, 48, 51) | the current writer agrees on every regenerated case |

## CI1 — the CI-only failure

Cause (from `gh run view --log-failed`): 11 tests needed git-ignored
`local_docs` PDFs; 2 ran `git show 56e80ca:…` on a depth-1 clone.
Change: a missing corpus file still FAILS on a workstation and SKIPS (file
named) only when `CI` is set (`tests/local_corpus.py`); the backend checkout
fetches full history; pytest runs with `-ra --durations=20`.
Not verified: a CI run after the push (no CI result was read back).

## Group A — silent wrong or missing values

- **A1** (job 42 Remit To Bank, job 51 Box 11 / Box 13). Cause: grounding
  proves a string is printed, not which slot it answers. Change:
  `engine/ownership.py` — a `Box N` value printed in another box is cleared
  (the box is blank, so the slot stays plainly empty with a note); checkbox
  options take an X by x-position; one value in two non-alias slots of which
  only one is witnessed loses the copy embedded in a longer line. The
  completeness gate counts a form-box amount only next to its own full
  caption (pitt's explainer pages raised false Box 7/8/11 flags). Tests:
  `tests/test_overnight_a1_a2.py`.
- **A2** (pitt Box 14 52.00 in the Box 12 band). A row of a box-coded table
  printed in another box never enters the band; Box 14 says "Box 14 has a
  second entry 52.00 X that has no slot"; each entry's code is in the
  comment.
- **A3** Locality 700102 → text; control number spacing `0000005712 UUQ`
  recovered from character gaps (`text_layer.mark_printed_spaces`, geometry
  only, prompts unchanged) and trimmed to its own box; money labels always
  show two decimals; years no separator; an identifier slot is no longer
  "more than one piece of information" for a 10-digit run. Tests:
  `tests/test_overnight_a3.py`. Two older tests that pinned "exactly the
  printed decimals" for MONEY labels were updated to the owner's A3 rule.
- **A4** (mammoth, 37 of 48 rows). `recover_lost_pages`: one page-targeted
  call per lost page (`PAGE_RECOVERY_MAX_CALLS`, default 4), merged in page
  order; a column header reprinted at the top of the next page is a
  continuation (Berkshire's titled second table is still a new region). A
  table missing WHOLE stays the second request's job (Run A contract).
  Tests: `tests/test_overnight_a4.py`.
- **A5** (job 54 second Form Type empty, unflagged). One printed form title
  fills the slot (`1099-INT`, machine_read `form_title`); several are an
  empty-flagged slot naming them. Tests: `tests/test_overnight_a5.py`.
- **A6** parity alone vs combined (same record, same block); one-entity
  fragment rows merged; `EXTRACTION_TEMPERATURE=0` on every extraction call,
  recorded per attempt. Tests: `tests/test_overnight_a6.py`.

## Group B — false flags

- **B1** dot leaders (jobs 53/54), glued line breaks (jobs 42/50), label-row
  quotes (job 40): a value is Low only when neither its quote nor the page
  holds it. Tests: `tests/test_overnight_b1.py`.
- **B2** (job 46, 28 red cells): placement also accepts a value aligned with
  its own column's values (`set_column_anchors`); a description swapped
  into Date still fires. The job 50 McGuire case does not reproduce on the
  current pipeline with either quote; it is pinned. Tests:
  `tests/test_overnight_b2.py`.
- **B3** (jobs 49, 52, mammoth): an empty widget confirms its slot empty (no
  reason, no second request); a fillable form's tables are confirmed empty
  when every filled figure is in a cell, or no filled box belongs to them;
  on a text layer a printed label counts only with its whole caption and a
  value-like token after it. Tests: `tests/test_overnight_b3.py`.
- **B4** (job 48: "12 empty and flagged", no grey cell): the slot writer
  visits every slot, so an empty-and-flagged slot is the grey cell with its
  comment. `tests/legend_check.py` measures any export. Tests:
  `tests/test_overnight_b4.py`.

## Group C — Run F review (13 strict xfails → 0)

F2 prose only on an explanatory page (or with no page to judge); F2 list
number only with no other figure on the line; F4 callout only when the line
prints the label's value; F5 a matrix column naming the statement is not
ambiguous; E9 a copy is cleared only when the page prints no heading for its
column; E11 trailing minus; E12 a reordered complete address grounds when
every comma part is a whole printed line of one block; `_on_page` refuses a
value assembled across columns. The F1–F5 cases still pass.

## Group D — Run E review

D1 period cue for matrix headings, short total labels, two side-by-side
tables (3 strict xfails → 0). D2 the D13 inventory asserts F10's two warnings
by grid and text. D3 T9's ambiguity text says what the prompt carries.

## Group E — review screen

- **E1** the API persisted the edit (Codex, pinned in
  `tests/test_overnight_e1.py` for edit and correct-and-accept, through
  GET /results twice and the Excel). The revert was stale frontend state:
  `frontend/lib/reviewRefresh.ts` invalidates review, job-results, job and
  jobs after every action, and the Extract page reads results through the
  `job-results` query. A failed save shows "Not saved: …".
- **E2** every page of the document is listed (page ledger / inventory), the
  page endpoint returns `page_count`, and the dialog has Previous / "Page n
  of N" / Next with the value list following the page.
  `docs/REVIEW_FLOW_MANUAL_CHECK.md` section F.

## Group M — models (offline)

- **M1** `CANDIDATES` (with the `-latest` aliases) removed;
  `GEMINI_MODEL_FALLBACKS` (default empty); a 404 fails naming the model.
- **M2** `document_results.model_used` stores the returned `modelVersion`;
  the Legend says "Extracted by: …"; the History job detail shows it.
- **M3** `docs/MODEL_MIGRATION.md`; `MODEL_PROFILES` + `GEMINI_MODEL_PROFILES`
  (gemini-2.5 request byte-for-byte unchanged; 3.x drops temperature and
  sends a thinking level); 3.x prices; `live_cap` configurable but never
  removable; `tools/model_matrix.py` written and **not run**.

## Group H — accounts and security

- **H1** append-only `audit_events`, `GET /api/admin/audit` (admin-only,
  paged, filtered, firm-scoped, in the all-routes isolation suite),
  `/admin/audit` page.
- **H2** `users.token_version`, checked on every request; bumped by password
  change / reset, disable, delete, firm deactivation and
  `POST /api/auth/logout-everywhere`.
- **H3** one policy (12+, not the username, not common, not a plain
  sequence) on create, reset, change and bootstrap.
- **H4** `RAW_RESPONSE_RETENTION_DAYS` (7; 0 = never stored), purged at start
  and daily; redaction test over the `[LLM-ATTEMPT]` line.

Tenant isolation: `tests/test_tenant_isolation.py` and the all-routes suite
pass (0 routes leak); two new routes were added to it.

## RUN-G — origin/review/run-g merged

9 of 10 strict xfails in `tests/test_batch1_real_defects.py` pass and their
markers are removed. **Item 9 is BLOCKED**: it asserts the 16 frozen staging
exports, written by the old writer; no code change can alter them, and
re-exporting needs their stored `extraction_json`. Re-export jobs 46, 48, 51
from staging with this code, then remove the marker.

## FINISH — final checks (2026-11-20)

- The last edit before the session restart (`engine/format_rules.py`: the
  party-name rule keyed on the label's HEAD NOUN, so `Employer ZIP` = 10111
  is no longer "a name field holds a figure") had never been tested. Run
  through `./tools/run_tests.ps1 -q`: green; committed on its own (c1902c3).
- Backend suite: 5,257 passed, 19 xfailed, 0 failed, 0 errors (counted from
  the progress output, not the exit code). The 19 xfails: batch-1 item 9
  (BLOCKED, below), round-2 absent-field email, the selection-state
  scenario, and 16 template-layout-audit gaps (T6/T10/T12/T14/T15/T18,
  F2/F3/F9/F10/F12) that predate this run.
- Harness replay: templated 98.7%, no-template 98.2%, structure 17/17 with
  17 exact row counts, invented 0, misfiled 0, defect rate 0.0% (both).
- Frozen scoreboard (`tests/acceptance/test_scoreboard.py`): silent defects
  35 before, 0 after; false flags 0 on every job (15, 19, 21, 25).
  (`python -m tests.tools.score_runs` still prints the RECORDED baseline
  table — Gate: FAIL, 35 silent — which is the "before" side by design.)
- Frontend: type-check clean, 73 of 73 tests, build OK.

## Rules chosen

- Party-name check: only the label's last word decides, so a property of a
  party (ZIP, SSN) is never treated as a name; an identifier word still
  exempts the slot.

- A1: a value that belongs to another slot is CLEARED (with a note), not
  flagged — the slot is blank on the page, and the rules say a slot with no
  data stays plainly empty. A copy that does not ground in its own quote is
  left as it is (already Low and flagged): a visible wrong value stays
  visible.
- A1 / RUN-G item 1: a bank slot holding a name printed elsewhere as a
  party, with no bank word anywhere near it, is cleared; a bank named once
  in a payment line is kept.
- A3: money labels show at least two decimals even where the document
  printed none (owner rule); more printed decimals are kept.
- A4: recovery is for a LOST PAGE of a table that came back; a table missing
  whole keeps the one second request and then NEEDS_ATTENTION.
- A5: several printed form titles → empty and flagged with the titles, not a
  choice.
- A6(c): the replay cache was recorded at temperature 0.1 and keys on it, so
  the offline suite and replay harness pin 0.1; production extracts at 0.
- B1: a quote the page DOES hold with the value not in it (or under its
  heading) stays Low — the stricter reading, and `test_ocr_page_origin`
  pins it.
- B3: on a fillable form an empty box is the form saying "empty".
- RUN-G item 7: a party-name slot holding a bare figure is flagged (level
  not moved), except identifier and W-2 locality labels.
- H2: a password change keeps THIS device signed in (the response carries
  its new token); every other session ends.
- H4: "do not retain by default" with "default 7" read as: never kept
  indefinitely; 7 days by default; 0 = never stored.

## Not verified

- No CI run was observed after the pushes.
- No live model call: every model behaviour here is scripted. The M3 3.x
  profiles (`thinkingLevel` in camelCase on generateContent, `responseSchema`,
  response field names) are from Google's pages and unverified until the
  owner runs `tools/model_matrix.py`.
- Google's pages were read on 2026-11-20 at `aistudio.google.com/docs/*`
  (the `ai.google.dev` URLs redirect there); pricing for 2.5 models was not
  on the pages read.
- The frontend changes (E1, E2, H1 page, H2 button) are covered by unit
  tests of their logic, a type-check and a build, not by a browser run;
  `docs/REVIEW_FLOW_MANUAL_CHECK.md` section F is the manual check.
- The Postgres startup DDL for `token_version` was not run against
  PostgreSQL here (SQLite tests use `create_all`).
- `tests/http/test_logs_carry_no_content.py` fails 3 tests when run directly
  after `tests/test_llm_router.py` + `tests/test_run_a_contract.py` (replay
  cache miss). Pre-existing — reproduced on the committed client — and the
  default full-suite order is green.
- The job 50 McGuire "different column" flag did not reproduce on the
  current pipeline; its cause in the staging run is unknown.
