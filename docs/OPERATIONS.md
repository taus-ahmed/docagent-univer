# Operations — for the person running DocAgent

No development knowledge assumed. Statements about Railway, Vercel, Cloudflare
or Google that cannot be checked from this repository are marked **VERIFY**:
check them in the provider's dashboard or terms before relying on them.

## 1. What runs where

A browser app (Next.js, on **Vercel**) talks to one backend (FastAPI, Python,
on **Railway**) at `https://loving-grace-production.up.railway.app`. The
backend keeps users, jobs, results and templates in **PostgreSQL** (a Railway
service), stores uploaded documents either on the container's own disk
(`STORAGE_BACKEND=local` — **lost at every deploy**) or in a **Cloudflare R2**
bucket (`STORAGE_BACKEND=s3`, [R2-SETUP.md](R2-SETUP.md)), and sends each
document to **Google Gemini** to read it. Extraction runs on a background thread
inside the one backend process; the app assumes **exactly one backend
instance** (see §9).

## 2. Environment variables

Set in the Railway dashboard (backend) and Vercel (frontend). **S** = secret
(never paste into chat, tickets or code), **E** = differs per environment
(staging vs production).

| Variable | Example | | What it does |
|---|---|---|---|
| `ENVIRONMENT` | `production` | E | `production` hides the API docs and refuses to boot on a placeholder key or a failed migration |
| `SECRET_KEY` | 64 hex chars (`openssl rand -hex 32`) | S E | signs sign-in tokens; changing it signs everyone out |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | | how long a sign-in lasts |
| `DATABASE_URL` | `postgresql://user:…@host:5432/db` | S E | the database (Railway provides it) |
| `GEMINI_API_KEY` | `AIza…` | S E | the model provider key |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | | the model (production runs flash-lite) |
| `PRIMARY_LLM` / `LLM_FALLBACKS` | `gemini` / empty | | provider order; only Gemini is a real provider. `stub` is a DEV-ONLY offline fake ([OFFLINE-DEMO.md](OFFLINE-DEMO.md)); the backend refuses to start with it when `ENVIRONMENT` is `staging` or `production` |
| `BATCH_SIZE`, `RATE_LIMIT_DELAY`, `MAX_RETRIES` | `5`, `2.0`, `3` | | pacing of model calls |
| `DEBUG` | `false` | | verbose errors; keep `false` in production |
| `STORAGE_BACKEND` | `s3` | E | `local` (ephemeral disk) or `s3` (R2) |
| `LOCAL_UPLOAD_DIR`, `LOCAL_OUTPUT_DIR`, `LOCAL_SCHEMAS_DIR` | `./storage/uploads`, … | | where `local` storage writes (relative to `backend/`) |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `AWS_REGION` | `docagent-prod`, `https://<acct>.r2.cloudflarestorage.com`, `auto` | E | the bucket |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | R2 token | S E | bucket credentials |
| `ALLOWED_ORIGINS` (or `CORS_ORIGINS`) | `https://your-frontend.vercel.app` | E | which site may call the API; unset = any (a warning at boot) |
| `MAX_UPLOAD_SIZE_MB` (alias `MAX_FILE_SIZE_MB`) | `50` | | per file |
| `MAX_PDF_PAGES` | `200` | | per PDF |
| `MAX_IMAGE_PIXELS` | `50000000` | | per image |
| `MAX_FILES_PER_BATCH` | `100` | | per upload |
| `TENANT_MONTHLY_PAGE_LIMIT` | `2000` | | pages per firm per calendar month; `0` = unlimited (default) |
| `DATA_RETENTION_DAYS` | `90` | | delete jobs this many days after they finish, daily; `0` = off (default) |
| `OPTION_MAX_CALLS_PER_JOB` | `20` | | model calls the additional options may make per job (the written summary); each also counts as one page toward the firm's monthly limit |
| `TRUSTED_PROXY_COUNT` | `1` | | proxies in front of the backend that each append one `X-Forwarded-For` entry; the login limiter trusts the N-th entry from the right (§9). `0` = ignore the header |
| `DRIVE_TENANT` | `smith_cpa` | | the one firm whose Google Drive the server's Drive credential is; empty = Drive off (default) |
| `DEMO_CLIENT_IDS`, `DEMO_MAX_MB`, `DEMO_MAX_UPLOADS`, `DEMO_UPLOADS_ENABLED`, `DEMO_HISTORY_CUTOFF` | `pearx_demo`, `10`, `20`, `true`, empty | | the investor demo; empty `DEMO_CLIENT_IDS` = no demo |
| `DOCAGENT_BOOTSTRAP_ADMIN_USERNAME`, `…_PASSWORD`, `…_DISPLAY_NAME` | | S | creates the first platform admin on an empty database; **remove the password variable right after** |
| `BCRYPT_ROUNDS` | `12` | | password hashing cost (tests use 4) |
| `OCR_WORKERS` | `2` | | OCR pool size per file; default min(4, CPUs); `1` = serial (§11) |
| `OCR_PROBE_TIMEOUT_S`, `OCR_RENDER_TIMEOUT_S`, `OCR_TESSERACT_TIMEOUT_S`, `OCR_PAGE_TIMEOUT_S`, `OCR_POOL_TIMEOUT_S` | `15`, `120`, `120`, `300`, `1800` | | deadlines for the page renderer and the OCR reader (§11) |
| `NEXT_PUBLIC_API_URL` (Vercel) | the backend URL | E | where the browser app sends requests |

Not read any more and safe to delete: `GROQ_*`. Not active yet (Phase 4):
`REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`.

## 3. Deploy and rollback

- **Both services deploy automatically when `main` changes** (Railway backend
  and frontend; Vercel if connected) — so nothing reaches `main` until it has
  passed the checks in [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md) and been
  tried on **staging** (§10).
- **What happens to the database on deploy:** at every boot the backend runs
  its own additive migrations (`main.py::_run_migrations`), creates missing
  tables, then serves. In production a failed migration stops the boot, and the
  healthcheck (`/health`, 120 s) keeps the previous deployment serving.
  Data is not rewritten. Alembic migrations are manual and none are pending.
- **Uploaded files on `STORAGE_BACKEND=local` are lost at every deploy**; job
  rows and results survive (they are in Postgres). Use R2 in production.
- **Rollback:** Railway → backend service → Deployments → pick the last good
  one → Redeploy (**VERIFY** the current dashboard wording). Vercel → Project →
  Deployments → "Promote to Production" on the previous one (**VERIFY**). A
  rollback of code does not roll back data; nothing in this release changes
  stored rows' shape (no migration this round).

## 4. Backups

- **Postgres:** Railway offers volume backups for its database services
  (**VERIFY**: whether they are enabled on this project, the schedule and how
  long they are kept). Independently, take your own: `pg_dump "$DATABASE_URL"
  > docagent-YYYYMMDD.sql` from a trusted machine, kept encrypted.
- **R2 bucket:** no backup exists unless you make one; object versioning is
  off by design so a delete really deletes (**VERIFY** in the Cloudflare
  dashboard). A copy (`rclone sync`) to a second bucket is the usual approach.
- **Test a restore** each quarter: restore the dump into a new, empty Railway
  Postgres (never the live one), point a staging backend at it, sign in, open a
  job. A backup never restored is a guess.
- Backups keep deleted data until they expire — say so to clients
  ([CLIENT-DATA-FAQ.md](CLIENT-DATA-FAQ.md)).

## 5. Monitoring

- **Uptime:** any uptime checker (UptimeRobot, Better Stack, …) on
  `GET /health` every 5 minutes, alert on non-200.
- **Errors:** Railway → backend → Logs (**VERIFY** retention). Search for
  `Traceback`, `[THREAD]`, `FAILED`, `[QUOTA]`, `[RETENTION]`.
- **What log lines mean:**

| Line | Meaning |
|---|---|
| `[JOB] … job N` | a job started, finished, or was cancelled |
| `[DELETE] job N: x files, y results` | a hard delete |
| `[RETENTION] n jobs purged [ids]` | the daily purge |
| `[QUOTA] refused: p pages, u/l used` | a firm hit its monthly page limit |
| `[AUTH] IP … locked out of one account` | 5 failed sign-ins from one address for one username |
| `[TENANCY] user N named another client_id` | someone asked for another firm; refused by design — repeated lines from one user are worth a look |
| `[TENANT] firm created with admin user N` | onboarding |

- **The opaque ids:** logs never contain a file name, a value or a firm name.
  A document appears as `doc-<10 hex>` — a hash of its file name. To find
  which one it was, compare it with the job's results (the same hash of
  `original_filename`); it cannot be reversed without the list.

## 6. Key rotation

| Key | How | Effect |
|---|---|---|
| Gemini | create a new key in Google AI Studio / Cloud console (**VERIFY** where yours lives), set `GEMINI_API_KEY`, redeploy, then delete the old key | none for users |
| `SECRET_KEY` | new value, redeploy | everyone is signed out (also the way to cut off a stolen token, since tokens are not revocable one by one) |
| Database password | rotate in Railway (**VERIFY** procedure), which updates `DATABASE_URL` for linked services | a restart |
| R2 token | new token in Cloudflare, set both `AWS_*`, redeploy, revoke the old | none |

## 7. Cost controls

- **Google:** set a budget alert and, if available for your billing account, a
  hard spending cap on the Gemini project (**VERIFY** what Google currently
  offers for the Gemini API).
- **Per firm:** `TENANT_MONTHLY_PAGE_LIMIT` (and `monthly_page_limit` in a
  firm's schema). Usage: `GET /api/admin/tenants` (every firm) or the Admin page.
- Upload limits (§2) cap the size of any one request.

## 8. Incident checklists

**Site down.** 1) `/health` from your machine. 2) Railway status page and the
backend's latest deployment state. 3) If the last deploy is the cause, roll
back (§3). 4) Database service up? 5) Note the time window for clients.

**Extraction failing.** 1) Logs for `[THREAD]` and the provider's HTTP status
(429 = rate limit, 403 = key/billing). 2) Google status page; key valid and
billing active (**VERIFY**). 3) A firm at its page limit sees a 429 message,
not a failure. 4) Jobs left `processing` by a restart are failed at the next
boot and say so — users re-upload.

**A client reports wrong values.** 1) Get the job id and the cell. 2) Open the
review screen: the value's status and the quote it was read from. A value not
marked verified was flagged for review by design. 3) If it was marked
verified and is wrong, keep the job (do not delete), export it, and record it
for the developer with the job id — that is a defect report.

**Suspected data exposure between firms.** 1) Do not delete anything; note
times and the user ids involved. 2) If ongoing: deactivate the affected
users or the firm (`POST /api/admin/tenants/{id}/deactivate`), or rotate
`SECRET_KEY` to sign everyone out. 3) Logs: `[TENANCY]` lines and the user
ids. 4) The isolation suite (`tests/http/test_tenant_isolation_all_routes.py`)
shows what is guaranteed; a gap there is the developer's first fix.
5) Your contractual/legal notification duties to the firms (**VERIFY** with
counsel).

**Leaked key.** Rotate it at once (§6), then check usage at the provider for
the window. A key in a git commit stays in history: revoke it, never rely on
deleting the commit.

## 9. Limits of the design

- **One backend instance.** The login limiter, the job threads, the restart
  recovery and the retention task live in the process. Running two would
  double the purge and split the limiter (needs Redis/Celery, Phase 4).
- **The login limiter trusts the `X-Forwarded-For` entry appended by the
  farthest trusted proxy**: with `TRUSTED_PROXY_COUNT=1` (default) the last
  entry, the address Railway's edge saw (**VERIFY** that Railway appends the
  client address as the last entry, and that nothing else between the edge
  and the app appends one). Put another proxy in front (a CDN, a load
  balancer) and raise it by one per proxy that appends an entry. Every entry
  to the left is whatever the caller sent and is ignored. With no header, or
  fewer entries than trusted proxies, the TCP peer is used. If the frontend
  calls through the Next.js proxy, every user shares Vercel's address; the
  limit is per (address, username), so a lockout still only affects one
  username.
- Login lockout: 5 failures → 15 minutes, per (address, username), in memory
  (reset by a restart).

## 10. Before changing anything on `main`

1. Make the change on a branch.
2. `python scripts/prepush_check.py` — suite, native readings, accuracy
   harness, frontend build ([RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md)).
3. Deploy that branch to a **staging** environment with its own database and
   bucket (Railway environments — **VERIFY** setup), sign in, upload a
   document, export it.
4. Only then merge to `main` — which deploys production immediately.

## 11. Page rendering and OCR deadlines

The backend starts two outside programs: Poppler (`pdftoppm`, `pdfinfo`) to
turn PDF pages into images, and Tesseract to read scanned pages. Every call
has a hard deadline; a call past it is **killed together with anything it
started**, and the page (or file) fails **with a message naming the program
and the setting** — it is never left hanging. A failed page is listed in the
document's notes and marked for review like any other unread page.

| Setting | Default | Bounds |
|---|---|---|
| `OCR_PROBE_TIMEOUT_S` | 15 s | `pdftoppm -v` / `tesseract --version`, asked **once per process** (the pool's workers are handed the answer); a failed probe is asked again after 5 minutes |
| `OCR_RENDER_TIMEOUT_S` | 120 s | one `pdftoppm` / `pdfinfo` call, **per page** rendered by it |
| `OCR_TESSERACT_TIMEOUT_S` | 120 s | one Tesseract call (a page is 1–3 calls) |
| `OCR_PAGE_TIMEOUT_S` | 300 s | the OCR pool waiting on any one page |
| `OCR_POOL_TIMEOUT_S` | 1800 s | the OCR pool on one file in total |

When the pool passes a deadline it is stopped (its workers and their tools
killed) and the remaining pages are read one at a time, each still under the
per-call deadlines; their OCR record carries `pool_fallback` saying why.
Cancelling a job stops the pool the same way.

**Tuning.** Raise `OCR_RENDER_TIMEOUT_S` / `OCR_TESSERACT_TIMEOUT_S` only if
logs show `did not finish within` on large, legitimate pages on a slow
container; lower them to fail faster. `OCR_WORKERS=1` reads serially (no pool),
which also avoids any problem particular to running tools in parallel. In the
logs look for `did not finish within`, `version probe failed`, and
`parallel OCR unavailable`.

## 12. Before the first deploy of this release: check the firm ids

From this release a firm id (`client_id`) is used **exactly as written** as
the folder its files live under, or refused — it is no longer silently
rewritten (two ids such as `a b` and `a_b` used to share one folder). A firm
whose id contains anything but letters, digits, `.`, `_` and `-` (or starts
or ends with one of the last three) can no longer upload.

1. Get the list of firm ids in production, one per line — from the Admin
   page, or ask whoever has database access for
   `SELECT DISTINCT client_id FROM users` (**do not** give the script database
   access; it never connects to anything).
2. Run, on any machine with Python:
   `python scripts/check_firm_ids.py ids.txt` (or pipe the list into it).
3. Every line must say `ok`; the exit code is 0. The live demo's id
   (`demo_001`, and whatever `DEMO_CLIENT_IDS` names) must pass.
4. A `REFUSED` id must be renamed to a valid one **and its files moved** from
   the folder the script names (`clients/<old folder>/…`) before that firm
   uploads again; a `COLLIDE` line means those firms' files already share a
   folder — stop and get the developer before deploying.
