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
- **Login rate limit**: 5 failed attempts per IP locks that IP out for 15
  minutes (`routes/auth.py`). It is in memory, so it resets on restart and does
  not span instances. `X-Forwarded-For` is trusted (Railway's proxy).

## Tenancy

- Every data table carries `client_id`. The tenant a request acts as comes from
  the **token, never the request body** (`extract.py::resolve_client_id`); a
  super-administrator (role `admin`, no `client_id`) must name the client.
- Hard delete: `DELETE /api/jobs/{id}/data` (tenant admin of the job's firm,
  platform admin) removes the job's stored files (sources, outputs; local or
  object store, verified gone before anything else changes), the review
  screen's cached page/OCR images and temp copies, and every result row; the
  job record stays with a `deleted` mark. Running jobs must be cancelled first
  (409). Logged as job id and counts only.
- Roles: one permission function, `app/core/permissions.py::can(user, action,
  resource)`, with the matrix as data (`docs/proposals/roles.md`, "As
  implemented"); routes never compare role strings themselves.
- Jobs: `_get_job_or_404` allows a super-administrator, an administrator or
  `company_admin` of the job's tenant, or the job's own user; any other id —
  another firm's included — answers 404 "Job not found", the same as a missing id.
- Templates: `load_template_for_user` checks ownership before an upload uses a
  template id; an unknown id fails rather than silently extracting without one.
- Watch folders (`drive._visible_watch_folders`): a super-administrator sees
  all, a tenant administrator its own tenant's, a user its own; any other id is
  a 404.
- A tenant comparison needs a tenant: `auth.same_tenant` treats a missing
  `client_id` as "no tenant", never as a tenant shared with every other account
  that has none (super-administrators' templates carry `client_id = NULL`).
- The flat exports (`/api/export/combined`, `/perfile`) accept only a template
  the caller could extract with (`load_template_for_user`), answered as 404.

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
| Platform admin is derived (`admin` with no `client_id`), not stored | `permissions.role_of` | one `UPDATE … SET client_id = NULL` makes a tenant admin a platform admin; explicit role needs a migration (`proposals/roles.md` step 3) |
