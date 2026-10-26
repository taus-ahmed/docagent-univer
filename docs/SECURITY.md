# Security notes

What the code does today, and the gaps that are known and open. Each statement
names the code that implements it.

## Authentication

- **JWT, HS256, stateless** (`app/core/auth.py`). The payload is
  `{sub: user id, role, client_id}`. Logout is a server no-op; the token expiry
  (`ACCESS_TOKEN_EXPIRE_MINUTES`) is the only invalidation.
- **`SECRET_KEY`**: a production boot refuses every shipped placeholder
  (`config.py::_PLACEHOLDER_SECRETS`,
  `_refuse_to_run_production_on_a_known_key`). Generate one with
  `openssl rand -hex 32`.
- **First administrator**: there is no default account. One is created at boot
  only from `DOCAGENT_BOOTSTRAP_ADMIN_USERNAME` / `_PASSWORD` when no
  administrator exists; known default passwords are refused
  (`main.py::_bootstrap_admin`). Remove the password variable after the first boot.
- **Passwords**: bcrypt (cost 12, `BCRYPT_ROUNDS`) over a SHA-256 pre-hash, so
  long passwords are not truncated (`auth.py::hash_password`). Hashes from the
  old scheme (one round of salted SHA-256) still verify, compared in constant
  time, and are replaced with bcrypt on the user's next successful login; no
  bulk migration. A user who never logs in again keeps the old hash. An
  unknown username spends one dummy bcrypt verify, so response time does not
  reveal which usernames exist.
- **Login rate limit**: 5 failed attempts for one username from one address
  lock that (address, username) out for 15 minutes (`routes/auth.py`). Keyed
  by the pair so nobody can lock out another firm's users: failures against a
  username lock only that username, only from that address. The address is
  the LAST `X-Forwarded-For` entry — the one Railway's proxy appends (⚠
  VERIFY); earlier entries are the caller's to choose and are ignored. In
  memory: resets on restart and does not span instances. A per-username lock
  across all addresses was rejected: it lets anyone lock a named user out.
- **One-time passwords**: an account created for someone else (onboarding,
  `scripts/create_tenant.py`, `POST /api/admin/tenants`, or a user created or
  reset with `must_change_password`) has its hash behind an `otp$` marker.
  It signs in, and every route but `GET /api/auth/me`, `POST
  /api/auth/change-password` and logout answers 403 until the user chooses a
  new password (at least 12 characters, proving the current one). No column:
  the marker lives in the hash it describes. The one-time password is shown
  once (script stdout or the create response) and never logged.
- **Firms**: created only by the platform admin (`POST /api/admin/tenants`) or
  the script, which refuses unless `--confirm-database` names the database's
  host class and never prints the database URL. Deactivating a firm
  deactivates every user (tokens stop working at once: `get_current_user`
  checks `is_active`); data stays.

## Tenancy

- Every data table carries `client_id`. The tenant a request acts as comes from
  the **token, never the request body** (`extract.py::resolve_client_id`, via `permissions.role_of`); a
  super-administrator (role `admin`, no `client_id`) must name the client.
- Hard delete: `DELETE /api/jobs/{id}/data?confirm=true` (the job's user, a
  tenant admin of the job's firm, platform admin) removes the job's stored files (sources, outputs; local or
  object store, verified gone before anything else changes), the review
  screen's cached page/OCR images and temp copies, and every result row; the
  job record stays with a `deleted` mark. Running jobs must be cancelled first
  (409). Logged as job id and counts only. Since round 14 the job's own user
  may do it too, and `?confirm=true` is required.
- Owner delete and retention (round 14): the job's own user may also
  hard-delete it; `?confirm=true` is required, without it nothing happens
  (400). `DATA_RETENTION_DAYS` > 0 starts a daily task that purges finished
  jobs older than the period through the same `purge_job`, one firm at a time
  with every query naming the firm (`core/retention.py`); 0 (default) starts
  nothing. Logged as job ids and counts. Per-firm periods and an audit table
  need a migration: `proposals/retention-v2.md`.
- Cost control: `TENANT_MONTHLY_PAGE_LIMIT` / a firm's `monthly_page_limit`
  (`core/usage.py`); refused before anything is stored (429).
- Cancel: `DELETE /api/jobs/{id}` — the owner, or an admin in scope; the job
  thread stops at its next checkpoint and lists unfinished files as cancelled
  (docs/ENGINE-RESULT-CONTRACT.md §1.2). Logged as job and user ids.
- Roles: one permission function, `app/core/permissions.py::can(user, action,
  resource)`, with the matrix as data (`docs/proposals/roles.md`, "As
  implemented"); routes never compare role strings themselves.
- Jobs: `_get_job_or_404` allows a super-administrator, an administrator or
  `company_admin` of the job's tenant, or the job's own user; any other id —
  another firm's included — answers 404 "Job not found", the same as a missing id.
- Templates: `load_template_for_user` checks visibility before an upload uses a
  template id; an unknown id fails rather than silently extracting without one.
  A template the caller cannot see (another firm's, a colleague's private one)
  answers 404 "Template not found" on every route, the same as a missing id; a
  visible one the caller may not change answers 403.
- Google Drive is ONE server-wide OAuth credential, so it belongs to one firm:
  `DRIVE_TENANT` (empty = Drive closed to everyone). Every other firm gets 403
  on browse, extract, watch and check, and "not configured" from the status
  route; Drive jobs and watch folders are always `DRIVE_TENANT`'s, and the
  watch check only ever hands the watcher that firm's folders.
- Watch folders (`drive._visible_watch_folders`): a super-administrator sees
  all, a tenant administrator its own tenant's, a user its own; any other id is
  a 404.
- A tenant comparison needs a tenant: `auth.same_tenant` treats a missing
  `client_id` as "no tenant", never as a tenant shared with every other account
  that has none (super-administrators' templates carry `client_id = NULL`).
- The flat exports (`/api/export/combined`, `/perfile`) accept only a template
  the caller could extract with (`load_template_for_user`), answered as 404.

## Isolation between firms

Proved by three suites; a route added without a case fails the first.

- `tests/http/test_tenant_isolation_all_routes.py` enumerates `app.routes`;
  every route is in `ROUTES` (how it is attacked) or `ALLOWLIST` (why it holds
  no firm's data). Firm B's admin, reviewer and user call every id route with
  firm A's ids and must get exactly the answer a missing id gets (status and
  body); lists, exports and downloads are scanned for firm A's markers;
  mutations are followed by a check that firm A's records are unchanged.
- `tests/http/test_tenant_side_channels.py` — storage keys, caches, headers, logs.
- `tests/http/test_tenant_concurrency.py` — two firms, 50 files each, uploaded
  at the same instant through the real route and job threads.

Audit (round 14), each with its evidence:

| Channel | Finding |
|---|---|
| Storage keys | `clients/{client_id}/jobs/{job_id}/…` from one place. A firm id is used **verbatim or refused** (`storage._tenant_segment`): normalising it let `a b` and `a_b`, or `../acme` and `acme`, share one prefix and one schema file. The API refuses such ids at creation (`CLIENT_ID_PATTERN`, users and schema upload). File names are normalised and cannot leave their job's folder. Job ids are global, so two firms never share a job folder. |
| Signed URLs | `signed_url` is capped at 1 hour, returns None on the local backend, and is not served by any route today. A key always names its firm. |
| Temp copies | random names (`NamedTemporaryFile`, prefix `copy-`) in the app's own directory, released on success, failure and cancel; never keyed by file name. |
| Page images | `Cache-Control: private, max-age=3600` — the viewer's own browser only. |
| Every other `/api/` response | `Cache-Control: no-store` and `Vary: Authorization` (`main.py` middleware), so no proxy, CDN or edge can replay one firm's answer to another caller. |
| Export file names | `job_{id}_results.xlsx`, `docagent_job{id}_….xlsx`, the firm's own file names inside its own zip — never a firm id. |
| In-process caches | The review screen's reading cache is keyed by storage key (which leads with the firm); tested with two firms storing the same file name. No other cache holds firm data: the prompt registry is static, the batch schema cache lives for one job, `gemini_client._good_model` holds a model name, OCR identity a version string, cancellation is per thread, the LLM record/replay cache is test-only. |
| Rate limiter | see "Authentication": keyed by client IP and username. |
| Logs | ids and counts only ("Logging" below). The tenancy line no longer prints the client id a user asked for or their own. |
| Error messages | identical for another firm's id and a missing id (tested route by route); a 404 may echo the id the caller sent, nothing else. |
| Drive watcher | only `DRIVE_TENANT`'s folders are processed (above). The engine's CLI loop (`engine/drive_watcher.py::run_loop`) is not reachable from the API. |

## Uploads and storage

- Limits: `MAX_UPLOAD_SIZE_MB` (alias `MAX_FILE_SIZE_MB`), `MAX_PDF_PAGES`,
  `MAX_IMAGE_PIXELS`, `MAX_FILES_PER_BATCH`; invalid values fall back to safe
  defaults.
- Storage keys are built in one place and validated by `storage._safe_key`
  (no `..`, absolute paths, drive letters, backslashes or empty segments); the
  local backend re-checks that the resolved path stays under the storage root.
  `client_id` leads every tenant-owned key.
- Exports are rebuilt from the stored result on every download, never stored.
- Object-store temp copies (`storage.get_local_path`, needed because the PDF
  readers want a path) live in the app's own directory (`storage.TEMP_COPY_DIR`)
  and are deleted by `release()` / `local_copy()` on success, failure and
  cancel; boot deletes copies older than a day from that directory only.
  `release()` never deletes the local store's own files.

## Logging

Logs leave the tenant boundary — the platform's log drain, whoever debugs a
deploy, a screenshot in a chat — so they carry **identifiers, counts,
durations and reason codes, never content**.

| May be logged | Never logged |
|---|---|
| job, document, user and watch-folder ids; `client_id` | document text, OCR text, extracted values, summaries, anomalies |
| `doc_ref(name)` — `doc-` + 10 hex of SHA-256 of the file's base name | the file name a client gave a document; Drive file and folder names |
| counts, page numbers, sizes, token counts, costs, timings | prompts and model answers, including an answer that failed to parse |
| `exc_brief(e)` — the exception's TYPE (and HTTP status) | exception messages and full tracebacks (they quote paths, names, parser input) |
| frames-only tracebacks (`print_safe_traceback`, file:line:function) | request bodies, query strings, provider error bodies |
| template structure: band and heading labels, cell refs | |
| the client IP on a login lockout (needed to act on it) | |

The helpers are in `backend/engine/log_safety.py`. `doc_ref` is stable, so one
document is one reference throughout a run, and whoever holds the database
(where the real name is stored) can recompute it to find the row.

Libraries that read documents log what they read below WARNING — pdfminer's
DEBUG lines are the page text verbatim — so `log_safety` caps `pdfminer`,
`pdfplumber`, `PIL`, `pypdf`, `pytesseract`, `pdf2image`, `urllib3`,
`botocore`, `boto3` and `s3transfer` at WARNING whatever the root level is.

Enforced by `tests/http/test_logs_carry_no_content.py`: real extractions
(templated with every option, no-template, a non-JSON model answer, an
unreadable file, a missing source) with a sentinel in the document text, the
file name, the model's answers and the option answers, and the sentinel must not
appear in stdout, stderr or any logger at any level. The engine's command-line
batch tool (`orchestrator.py`, `rich` console) prints to the operator's own
terminal and is outside this policy.

Not covered: template labels are logged as structure. They are the client's
template, or — with no template — field names the model chose from the page
(`Invoice Number`), not values.

## Secrets

- `.env` files are ignored by git. `backend/.env.example` lists every variable
  with placeholder values only.
- The model provider key (`GEMINI_API_KEY`) is read from the environment and
  sent only to the provider's API.
- ⚠ An old commit on `main` (`ecaead9`, 2026-04-26) contains a Groq API key in
  `.env.example`. It was replaced in the next change but remains in history;
  the key must be treated as compromised and revoked at the provider.

## Known gaps

| Gap | Where | Note |
|---|---|---|
| A password change does not invalidate issued tokens | `auth.py` | needs a token version or deny list |
| Rate limiter is per process | `routes/auth.py` | needs a shared store before running more than one instance |
| Page-limit check is atomic per process only | `core/usage.py` | two instances could both admit the last pages |
| One retention period for every firm; no audit trail | `core/retention.py` | `proposals/retention-v2.md` (migration) |
| Platform admin is derived (`admin` with no `client_id`), not stored | `permissions.role_of` | one `UPDATE … SET client_id = NULL` makes a tenant admin a platform admin; explicit role needs a migration (`proposals/roles.md` step 3) |
