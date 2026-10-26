# Data retention and privacy

**Status (reconciled in Run 15 — the code wins where this text and the
code differ; [../SECURITY.md](../SECURITY.md) is the current statement):**

| Item | State |
|---|---|
| Per-job hard delete | **implemented** — `DELETE /api/jobs/{id}/data?confirm=true` (`core/job_lifecycle.py::purge_job`) for the job's **owner**, a tenant admin of its firm, or a platform admin (owner delete decided in round 14); the job record stays with a `deleted` mark in `notes` (no migration) |
| Retention period + daily purge | **implemented, global only** — `DATA_RETENTION_DAYS` (`core/retention.py`, round 14); per-firm periods are in [retention-v2.md](retention-v2.md) |
| Temp copies of documents | **released** — after each job file (`job_worker._release_copy`), when the review screen's cache evicts a file (`routes/review.py`), and by an age sweep at boot (`main.py::_sweep_temp_copies`) |
| Watch folders | **firm-scoped** (round 13); Google Drive is closed to every firm but `DRIVE_TENANT` (round 14) |
| Content in logs | **removed** — documents appear as `doc-<hash>`, errors by type; template text removed from the last log lines in Run 15 (`tests/http/test_logs_carry_no_content.py`, `tests/test_export_logs_carry_no_content.py`) |
| Review marks overwriting each other | **fixed** in Run 15 (compare-and-swap, `routes/review.py`) |
| Per-firm delete, audit table, per-firm period | **open** — need a migration; [retention-v2.md](retention-v2.md) |

The inventory below is kept as it was taken (2026-10-23), with each row that
has since changed marked **[changed]**.

Inventory taken 2026-10-23 from the code
at `integration/ocr-hardening`. Statements about Railway, Cloudflare and Google
are what their published terms said as of my knowledge and **must be checked
against the current terms and the account's actual settings** before they are
given to a client. They are marked ⚠ VERIFY.

## What is stored, where, and who can read it

| Data | Where | Written by | Who can read it through the app | Lifetime today |
|---|---|---|---|---|
| Original uploaded files | object store (`STORAGE_BACKEND=s3`, Cloudflare R2 in production) or local disk, key `clients/{client_id}/jobs/{job_id}/source/{name}` (`core/storage.py`) | upload, Drive import | job access (`_get_job_or_404`) — the review page-image route re-reads the file | **forever** |
| Temporary copies of uploaded files | container `/tmp` (`storage.get_local_path` → `NamedTemporaryFile(delete=False)`) | every job and every review page-image read on R2 | nobody via the app; anyone with shell access to the container | **[changed]** released after use and swept at boot (was: until the container restarts) |
| Extraction results (every value, its source quote, page, confidence, review marks) | PostgreSQL `document_results.extraction_json` | job runner, cell edits, review marks | job access | forever |
| Raw model response | PostgreSQL `document_results.raw_llm_response` | job runner | not exposed by any route; database access only | forever |
| Page images (straightened scans, rendered pages) | **not stored**: computed on request, held in an in-process LRU of 6 files (`routes/review.py:46`) | review page-image route | job access | process memory, evicted |
| OCR images | **not stored**: `ProcessedDocument.ocr_images`, memory only | preprocessor | — | the request / job |
| Exports (xlsx, zip) | **not stored**: rebuilt from `extraction_json` on every download (`save_output` is called by no route) | export routes | job access | — |
| Templates | `column_templates.description` | template editor | tenant (and shared/default) | until deleted by owner/admin |
| Client schemas | `client_schemas.yaml_content` + a copy in storage | schema upload | tenant; super-admin | until deleted |
| Users | `users` (username, display name, e-mail, bcrypt hash, role, tenant, last login) | admin | tenant admin; super-admin | forever; "delete" deactivates |
| Drive OAuth / watch folders | `watch_folders` (folder ids, processed file ids); OAuth credentials file on the server | Drive routes | owner; **[changed]** firm-scoped since round 13, Drive closed but for `DRIVE_TENANT` since round 14 | forever |
| Demo activity log | `demo_activity` (filenames, sizes, template names; never contents) | demo tenant only | database access only | forever, by design (append-only) |
| Application logs | Railway log stream (stdout) | `print` throughout | Railway project members | Railway's log retention ⚠ VERIFY |

**[changed — no longer true, see the status table]** **Logs do carry document content.** Most lines are counts and statuses, but
some quote document text: `[EXPORT] layout: SKIP … ('<template text>')`, flag
summaries naming field values, `[TENANCY]` lines naming client ids, and every
uncaught exception's message. Filenames appear throughout. Treat the log
stream as containing client data.

**Copies outside our systems.** Each document's text — and, for scans and
images, page images — is sent to the model provider (Google Gemini API) for
every extraction (`connectors/llm_router.py`).

## How deletion works today

| Scope | What exists |
|---|---|
| One file | nothing |
| One job | **[changed]** `DELETE /api/jobs/{id}/data?confirm=true` hard-deletes (owner, firm admin, platform admin); `DELETE /api/jobs/{id}` still only **cancels** a running job |
| One user | `DELETE /api/admin/users/{id}` sets `is_active = False`; the user's jobs, results and files remain |
| One tenant | nothing; `DELETE /api/schemas/{client_id}` removes only the schema |
| Everything older than N days | **[changed]** `DATA_RETENTION_DAYS` daily purge (global) |

The `document_results.job_id` foreign key cascades on delete
(`models.py:105`), so deleting a job row would take its results with it — but
no code path deletes a job row.

## What is missing (as of 2026-10-23; items 1–3 and 6 are now addressed, see the status table)

1. No retention period: every client document and every extracted value is
   kept indefinitely.
2. No deletion a client can request and receive — not per file, job or tenant.
3. Temp copies of documents on the container are never removed.
4. No audit trail of who viewed, exported, edited or deleted what (only the
   demo tenant's activity log, and review marks overwrite one another).
5. The raw model response duplicates the extracted data and is read by nothing.
6. Content in logs.

## Recommended design

**Retention.** A per-tenant setting `retention_days`, default **90 days** after
the job completes, minimum 7, maximum 7 years (accounting records are commonly
kept 6–7 years, but that is the *client's* obligation for *their* books; the
copy we hold is a working copy). Original files, results and the raw response
go at the deadline; the job row stays as a tombstone (`status = "purged"`,
counts, timestamps, no content) so history and billing still add up.

**Hard delete**, three entry points sharing one function
`purge_job(job_id, actor, reason)`:

* per job — `DELETE /api/jobs/{id}/data` (owner, tenant_admin, platform_admin);
* per tenant — `DELETE /api/admin/tenants/{client_id}/data` (platform_admin,
  with the tenant name typed back as confirmation);
* scheduled — a daily sweep calling `purge_job` for every job past its
  tenant's retention.

`purge_job` deletes storage objects first (`delete_job_sources` and the output
prefix), then sets `extraction_json` and `raw_llm_response` to NULL, then marks
the job purged — in that order, so a failure half way leaves an orphaned row
(visible, retried by the sweep) rather than an orphaned file (invisible).
Deleted means deleted from the primary store; database backups and R2 object
versions age out on their own schedules, which must be stated to the client
(⚠ VERIFY Railway backup retention; keep R2 versioning off for this bucket).

**Audit trail.** An append-only `audit_events` table on the `demo_activity`
pattern (no foreign keys, never updated): who, when, tenant, action
(`upload`, `view_results`, `export`, `edit`, `review`, `purge`, `user_change`),
job/doc ids, and no document content. Kept longer than the data it describes
(default 2 years), because it is the evidence that a deletion happened.

**Smaller fixes, no design needed:** unlink the temp file after each job and
each page-image read; stop storing `raw_llm_response` (or purge it after 7
days); replace content-bearing `print`s with ids.

All of this needs a migration (`retention_days`, `audit_events`, the purged
status) and a product decision on the default period — hence a proposal.

## What an accountant client will ask, and the answers to prepare

| Question | Answer today | To do |
|---|---|---|
| Where does my data live? | Database on Railway (region = the project's region ⚠ VERIFY); files on Cloudflare R2 (bucket location hint ⚠ VERIFY); processing on Railway; text and page images sent to Google's Gemini API | write the regions down; offer EU-only if the client needs it (R2 jurisdiction setting, Railway EU region, Gemini regional endpoint ⚠ VERIFY availability) |
| Is it encrypted at rest? | R2 encrypts all objects at rest (Cloudflare's published default ⚠ VERIFY). Railway volumes ⚠ VERIFY. The application adds no encryption of its own | confirm both; consider column-level encryption of `extraction_json` only if a client requires it |
| In transit? | HTTPS to the app (Railway/Vercel), TLS to R2 and to the Gemini API | — |
| Subprocessors? | Railway (hosting, database, logs), Vercel (frontend), Cloudflare (file storage), Google (model provider) | a subprocessor list on the website, with a change-notice commitment |
| Does the model provider train on my documents? | Google's terms for the **paid** Gemini API say prompts and responses are not used to improve products; the **free tier** may be used for improvement ⚠ VERIFY the current terms, and that the production key is on a paid (billing-enabled) project | confirm the key's tier in writing; never use a free-tier key in production |
| Does the provider keep my documents? | Google retains API inputs for a limited period for abuse monitoring ⚠ VERIFY the period and whether zero-retention is available for this account | record the answer |
| How long do you keep my data, and can I delete it? | **[changed]** `DATA_RETENTION_DAYS` (off by default); a job can be deleted on request | the design above |
| Who at your company can see my data? | anyone with access to the Railway project (database, logs) or the R2 bucket | named list; least-privilege tokens; access through the audit trail |
| Can other clients see my data? | No by design: every table is filtered by `client_id` from the token, and every route is in the isolation suite (`tests/http/test_tenant_isolation_all_routes.py`). **[changed]** the watch-folder exception was fixed in round 13 | — |
