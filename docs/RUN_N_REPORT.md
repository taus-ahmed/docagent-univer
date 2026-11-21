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

## Rules chosen

## Not verified

- The Group H PostgreSQL DDL against a real PostgreSQL server (see N0).
