# Run N report — fix/review-fixes (from 873537c)

## Migration safety (N0)

Compared against the previous production build, commit 4c179b0
(`git diff 4c179b0 HEAD -- backend/app/main.py backend/app/models/models.py`).

**(a) Does the Group H migration only ADD things, with defaults for existing rows?**
Yes. Two schema changes, both additive:
- `users.token_version` — added by the startup statement
  `ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0`.
  PostgreSQL fills every existing row with 0 as the column is added, so no
  row is left NULL and the NOT NULL holds. The ORM also declares
  `server_default="0"`.
- `audit_events` — a brand-new table (plus its indexes), created by
  `init_db()` → `Base.metadata.create_all`, which only creates tables that
  do not exist yet. No existing table is altered by it.
Nothing is renamed, dropped or retyped.

One DATA change, not a schema change, that is not reversible: H4's raw
response purge runs at startup and clears (`SET NULL`)
`document_results.raw_llm_response` on every row older than 7 days
(`RAW_RESPONSE_RETENTION_DAYS`). `extraction_json` — the extraction, the
review edits and every export — is untouched. Only the diagnostic copy of
the model's raw answer is lost. If those old raw answers are wanted, set
`RAW_RESPONSE_RETENTION_DAYS` high before the deploy; otherwise this is the
intended behaviour.

**(b) Would the previous build (4c179b0) still start and work on a database migrated by this one?**
Yes. The previous build does not know `token_version` or `audit_events`:
- Its `User` model does not select or write `token_version`; when it creates
  a user, PostgreSQL's DEFAULT 0 fills the column, so the NOT NULL is never
  violated.
- `audit_events` is an extra table it never touches.
- Its own startup statements are all `IF NOT EXISTS` / `IF EXISTS`, so they
  apply cleanly over the newer schema.
What a rollback loses: revocation. The old build ignores `tv` in tokens, so
a token revoked on the new build (password change, disable,
"sign out everywhere") is valid again on the old one until it expires. No
audit rows are written while the old build runs. Neither stops it starting.

**(c) How do migrations run on Railway at startup, and what if one fails?**
There is no separate migration step: the container's entrypoint
(`backend/docker-entrypoint.sh`) only starts uvicorn, and the app's startup
(`main.py` lifespan) runs `init_db()` (create missing tables) and then
`_run_migrations()` (the idempotent `ALTER … IF NOT EXISTS` list), each
statement in its own transaction. Alembic is not run on Railway. A failed
statement is rolled back and logged as `MIGRATION FAILED: <sql>`; with
`ENVIRONMENT=production` any failure raises, the app refuses to serve, the
`/health` healthcheck fails, and Railway keeps the previous deployment
serving. The statements already applied stay applied — which (b) shows is
harmless to the previous build.

**(d) Can the existing user (Luq) log in after the deploy?**
Yes.
- Token version: Luq's row gets `token_version = 0`. A token issued before
  the deploy carries no `tv`, and `get_current_user` counts a missing `tv`
  as 0 (`core/auth.py`), so even an existing session keeps working; a new
  login issues `tv = 0`.
- Password policy: `password_policy.enforce` is called only on user create
  and admin reset (`routes/admin.py`), on `PUT /me` with a password and on
  change-password (`routes/auth.py`), and on bootstrap. The login route
  calls `verify_password` only, so a password that would fail the new
  12-character rule still logs in. Bootstrap runs only when no administrator
  exists at all, so it cannot refuse a database that already has one.
- The legacy `salt:sha256` hash still verifies and is upgraded on login, as
  before.

**SAFE TO DEPLOY** — with one stated consequence: raw model responses older
than 7 days are cleared at the first boot (set `RAW_RESPONSE_RETENTION_DAYS`
higher first if they are wanted). Not verified here: the PostgreSQL DDL was
not run against a PostgreSQL server in this session (the suite uses SQLite
`create_all`); the reading above is from the code.

## Before → after

| measure | before (873537c + run-h merge) | after |
|---|---|---|
| strict xfails, `test_overnight_ae_adversarial_review.py` | 7 | 0 (22 controls still pass) |
| backend suite | 5,257 passed, 19 xfailed at 873537c; the merge adds 22 passed + 7 strict xfails | 5,288 passed, 19 xfailed, 0 failed, 0 errors (exit 0; counted from the progress output) — +7 fixed reviews, +2 `tests/test_run_n.py` |
| harness templated / no-template | 98.7% / 98.2%, 17/17 | 98.7% / 98.2%, 17/17, invented 0, misfiled 0, defects 0.0% |
| harness Low / flagged cells | templated 5 Low, no-template 31 Low+flag lines | identical, cell for cell, to the pre-N2 commit 62f3955 (both modes) |
| frozen scoreboard | silent 0, false flags 0 | silent 0, false flags 0 (jobs 15, 19, 21, 25) |
| frontend | 73/73, type-check, build | 73/73, type-check clean, build OK (no frontend change) |

## N1 — merge origin/review/run-h

Merged; the only conflict was `tests/KNOWN_FAILING.md`, resolved by keeping
both sides (the batch-1 item 9 row and the seven new rows). 22 passed and 7
strict xfails on the merged tip (62f3955).

## N2 — B1: grounding by the quote's own row (2efc015, 4f67f46)

Cause: `verify_span` accepted a quote it could match as an ordered run of
words across consecutive lines (`in_line_order`), so `Opening Balance 170.00`
matched "Opening Balance" on one line and "170.00" on the next row, `Closing
Balance 170.00`. The B4 re-anchor also replaced an unfound quote with the
first line printing the value that shared a label word ("balance").
Change: `quote_row_lines` takes the quote's words that are not the value's
(letters only, so a figure never names a row) and finds the lines carrying
all of them — the row the quote names. `value_off_its_row` is True when the
value, as a whole token (`value_on_line`, so 170.00 ≠ 1170.00), is on none
of that row's lines. A quote printed verbatim on one line is its own row; a
quote that names no row (a glued line break, a quote that is only the value)
leaves the older rules in charge, so the Group B dot-leader, glued-line and
label-row cases are unchanged. Re-anchoring only moves to a line of the
named row. Follow-up: the harness showed one correct value demoted —
EXP-2024-0081 prints Purpose wrapped ABOVE its label — so a neighbouring
line (up to 3, above or below) whose every word is the quote's own is part
of the row, and a text value whose words are all in that block is on it.
Tests: `test_b1_wrong_value_on_another_row_is_not_grounded_via_an_invented_quote`
(marker off), `tests/test_run_n.py` (wrapped above the label; the
neighbouring-row unit case), `tests/test_overnight_b1.py` unchanged.
Not fixed: a value on its quote's row but in the wrong place ON that row is
still placement's job, not grounding's.

## N3 — B2: wrong column by the value's own position (10373f7)

Cause: `_inside_another_cell` (Run E, E10) skipped the placement check for
any value that was a word inside another cell of the row — meant for a unit
`(pair)` in a description, it also skipped an amount `70.00` copied out of
`Service 70.00`. Change: a value containing a digit is never exempted; it is
located on the line and judged by where it sits (the existing "later
occurrence" rule still withdraws a verdict when the figure is printed again
under its own column). The mammoth ATM WITHDRAWAL / MOBILE DEPOSIT rows and
the E10 unit case still pass. Tests: the B2 marker off; `test_overnight_b2.py`,
`test_batch1_real_defects.py`, `test_run_e_adversarial_review.py`.

## N4 — A1: an equidistant X (0acc02f)

Cause: `checkbox_marks` assigned each X to `min(distance)`, so a tie went to
the first option. Change: options whose distance is within `TIE_PT` (0.5 pt)
of the nearest are TIED; each gets the verdict None (the page does not say).
Nothing is moved or cleared for a tied option; the slot the answer marked is
kept, set Low, and flagged "ambiguous: the X on the page sits exactly between
'Box 13 Alpha' and 'Box 13 Beta', so the page does not say which box 13
option is checked". An X whose centre is inside one option's span, or
clearly nearer one, is still assigned by geometry. Tests: A1 marker off;
`test_overnight_a1_a2.py`.

## N5 — A6: fragment merge only from one record (deb748a)

Cause: `merge_fragment_rows` took "one keyed first row + keyless rows with
disjoint columns" as proof of one entity; Savings-B's credit (key missed)
was merged into Checking-A. Change: a fragment merges only when it was read
from the keyed row's record — the model's quote for it (kept from before
re-anchoring rewrote it to a line) equals the keyed row's quote, or prints
the keyed row's key as a whole word. No quote, no merge. pitt's three
state/local fragments (one quoted line) still merge into one row. Tests: A6
marker off; `test_overnight_a6.py`; the A6 control.

## N6 — A4: the recovery cap never silently omits a page (8d00017)

Cause: `recover_lost_pages` called `sorted(want)[:cap]` and dropped the rest
without a word; the document-level shortfall tolerated it. Change: every
qualifying page past `PAGE_RECOVERY_MAX_CALLS` is recorded and, unless the
final rows include that page after all, raises the reason "Page 6 was not
recovered: it prints about 2 rows of table 'Rows' that the answer left out,
and the limit of page recovery requests (PAGE_RECOVERY_MAX_CALLS) was
reached before page 6. Its rows are missing." — so the document is
NEEDS_ATTENTION. Tests: A4 marker off (the test now also asserts
NEEDS_ATTENTION); `test_overnight_a4.py`.
Not fixed: the cap itself (default 4) is unchanged; a page past it is
reported, not recovered.

## N7 — B3: one unplaced widget, one missed word value (c6b8a4d)

Cause: unplaced filled widgets were reported only at ≥3 and ≥ half; a word
value beside its label was never a signal (only a digit was). Change: below
the batch threshold each filled widget in no cell is a reason naming the
field and its value ("The filled form field 'Client Reference' on page 1
holds 'ZX-9', which matches no slot of the template and is not in any
cell"; it names the slot when one matches). An empty slot whose WHOLE
caption (every word, generic ones too) is printed with a capitalised word
value right after it, not in any cell, is flagged empty with the value and
raises "\"Employee Name\" is printed on page 1 with \"Alice Rivera\" beside
it, but that value is not in any cell." Blank widgets have no value and are
never reported: irs_w2_2012 and irs_1099int_mod3 stay READY with no reason.
Tests: both B3 markers off; `test_overnight_b3.py`, `test_overnight_a5.py`.

## Rules chosen

- N2: the quote's row is identified by its non-value words with letters; a
  figure never identifies a row. A neighbouring line belongs to the row only
  if every word on it is in the quote (stricter than "the next line").
- N4: the tie tolerance is 0.5 pt; a tied X keeps the model's answer, Low
  and flagged, rather than clearing it (a visible value over a silent
  blank — the review allowed either "empty and flagged" or "pick by span";
  the test pins the answer kept and the other option empty).
- N5: "same record" is the model's quote, not the re-anchored line,
  because re-anchoring rewrites every pitt fragment's quote to a different
  line.
- N6: the reason is raised unless rows from that page are in the final
  answer.
- N7: the address lines of a form party whose NAME slot is filled
  (street/address/city/town/zip/postal/country/apt in the field's label) are
  not reported: the template captures that party and did not ask for its
  address. This is what keeps irs_1099int_mod3's recipient address quiet;
  any other unplaced filled widget is reported. A missed word value must
  start with a capital and carry no digit (a digit is the older case), so a
  lower-case instruction sentence after a caption is not a value.

## Not verified

- The Group H PostgreSQL DDL against a real PostgreSQL server (see N0).
- No live model call; every model behaviour is scripted. The N7 word-value
  rule and the N6 reason have not met a real document that triggers them —
  the corpus and the frozen scoreboard raise neither (0 false flags).
- No CI run was observed after the pushes.
