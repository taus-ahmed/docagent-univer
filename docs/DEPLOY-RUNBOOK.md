# Deploy runbook — `feat/accuracy-harness` → Railway production

Rewritten 2026-08-24 at `836ea68`. Supersedes the 2026-08-19 revision, which
was written 32 commits ago and is stale in six places (test counts, storage
backend, schema materialisation, migration failure behaviour, job status, and
two total-failure bugs found since).

**Nothing has been deployed.** Every fact below was read from the live Railway
project or the production database read-only, or from the code at `836ea68`.

Work top to bottom. Do not start a step until the previous one verified.

---

## 0. Facts you need before you start

| | |
|---|---|
| Project | `8152d4bc-8029-49b2-8432-f23d13deb88b` (`resilient-youthfulness`), environment `production` (`f7eebaf4-…`) |
| Backend service | `1f378431-2df2-4e45-ba41-1297cc2d532d` (`docagent-univer`) |
| Frontend service | `33271ebb-6a2a-4acf-a7e4-c6311c64ee4c` (`loving-grace`) |
| Postgres service | `a074e1e1-6723-4121-9959-fd82574129d4` |
| **Live backend deployment** | `92b54699-a53f-4486-a636-570b4ac9df19`, commit **`2584bb6`**, deployed 2026-08-18 04:16 UTC, status SUCCESS |
| Deploy diff | the commits on `feat/accuracy-harness`; `2584bb6` is its merge-base, so no unrelated drift |
| Both services build from | branch **`main`** — nothing ships until you merge |
| Autodeploy | off |
| Healthcheck | `railway.json` sets `deploy.healthcheckPath=/health`, `healthcheckTimeout=120`. **The live deployment predates that file**, so `get-service-config` still shows no healthcheck: it takes effect on the deploy you are about to make. Config in code overrides the dashboard |
| Backend volume | **none mounted.** `./storage` is the container's ephemeral overlay filesystem and is new at every deploy. This is the whole reason Phase 8 exists |

Production data, read 2026-08-24:

| | |
|---|---|
| jobs | 163 (159 completed, 4 failed), 2026-05-02 → **2026-07-06** |
| document results | 222 |
| results with extracted values | 201 (21 completed rows hold no `extraction_json`) |
| results with a raw LLM response | 65 |
| templates | 19 |
| client schemas | 1 (`demo_001`, 7 391 bytes) |
| `column_templates.cell_binding_map` | still present — this deploy drops it |
| `column_templates.shape_json` | absent; it never shipped |

---

## 1. What changes

### 1.1 Database

| change | reversible? |
|---|---|
| `column_templates.cell_binding_map` **DROPPED** | **Yes** — `2584bb6` re-creates it on boot. See §6 |
| `column_templates.shape_json` `DROP IF EXISTS` | **No-op** — verified absent in production |

Nothing added, renamed or migrated. The one row holding a `cell_binding_map`
is template id 24 (`Invoice-Template-101`); its content is derivable from that
template's unchanged grid.

⚠ **Changed since the last revision — migrations now fail loudly.** The old
text here said each ALTER is wrapped in `try/except` and "cannot stop the
service starting". That is no longer true, and the change was deliberate
(`62f2558`). A statement that does not apply to this dialect is SKIPPED with a
reason; a statement that fails is logged at ERROR with the SQL; and **any
failure plus `ENVIRONMENT=production` raises and refuses to serve**. On Railway
that fails the healthcheck and the previous deployment keeps serving, which is
the outcome you want from a migration that could not run.

### 1.2 Storage — the substantive change in this deploy

Phase 8 put every file behind one key namespace with two backends:

```
clients/{client_id}/jobs/{job_id}/source/{filename}
clients/{client_id}/jobs/{job_id}/output/{filename}
schemas/clients/{client_id}.yaml
```

- The worker is handed **keys**, not paths. `_resolve_source` still accepts an
  absolute path, so a job queued before the upgrade would still run.
- `STORAGE_BACKEND=local` keeps today's behaviour exactly: the key is the path
  under the storage root. **You can deploy this without touching R2.**
- `STORAGE_BACKEND=s3` plus credentials switches to any S3-compatible store.
  No route changes. `boto3==1.34.144` is already in `requirements.txt`.

⚠ **`_materialise_schemas` — this is the bug that has been breaking
production.** A schema lives twice: the text in `client_schemas.yaml_content`,
and a copy on disk that `get_schema_path()` hands the engine. With no volume
the disk copy dies at every redeploy, and `_seed_demo_schema` returns early
whenever the table is non-empty — which it always is after the first boot. So
**from the second deploy onward there was no YAML on disk and
`POST /api/extract/upload` answered `404 "No schema found."` for every
upload.** `main.py::_materialise_schemas()` writes them back from the database
at boot, idempotently. Verified in §5 step 3.

**Exports were never stored** and still are not: `GET /api/jobs/{id}/export`
rebuilds the workbook from `extraction_json` on every download. Nothing needed
migrating and nothing is lost on restart.

**Source documents for the 222 historical results are unrecoverable** and this
deploy does not pretend otherwise — see §3.

### 1.3 Job status gains `partial`, and a failed document leaves a row

`extraction_jobs.status` was `pending | processing | completed | failed |
cancelled`. It is now `pending | processing | completed | partial | failed |
cancelled`, and a terminal status states what the batch **produced**:

| status | meaning |
|---|---|
| `completed` | every document returned a result |
| `partial` | some documents returned results, some failed |
| `failed` | none did |

Previously a job where every document failed reported `completed` with
`successful=0`. A document that failed before producing a result left **no
`DocumentResult` row at all**, so the results grid was empty, the export
answered 404, and nothing anywhere said why. Both are fixed: the status names
the outcome, and every failed document persists a row carrying its filename and
the exception in `validation_errors`.

**Frontend follows the same vocabulary** — amber badge and warning icon for
`partial`, polling stops on it, results and downloads still load (a partial job
has real output for the documents that worked), and Analytics counts partial
jobs as work done rather than dropping their spend.

No API shape changed: `status` was always a plain string.

### 1.4 Two total-failure bugs, found and fixed after the last revision

Both are **branch-only**. Slot extraction is not an ancestor of `2584bb6`, so
neither has ever run in production — but both would have shipped in this deploy.

| # | commit | what it did |
|---|---|---|
| 1 | `6e4eaf4` | `_run_extraction_sync` referenced `storage`, a name that exists only as a request dependency on the upload route. NameError on the first line of every document's try block → **every document of every upload failed**, while the job reported `completed` |
| 2 | `f5b7ad6` | `validation.flagged_fields` had three shapes and both readers assumed one. The save path indexed `f['ref']`, which raises `TypeError` on a string → **any document carrying one flagged field failed to save** |

The second was only visible once the first stopped hiding it. Both are now
covered by `tests/http/test_batch_end_to_end.py`, and a pyflakes gate
(`tests/test_no_undefined_names.py`) runs on every commit so a third undefined
name cannot ship the same way.

### 1.5 Config

- **CORS reads configuration.** `settings.cors_origins` accepts `CORS_ORIGINS`
  (what production sets) or `ALLOWED_ORIGINS` (what the code declared).
  `allow_credentials` stays `False` — the frontend authenticates with a Bearer
  token from `localStorage`, not a cookie.
- **`MAX_FILE_SIZE_MB` is read**, aliased to `MAX_UPLOAD_SIZE_MB`. Both are 50,
  so no behaviour change today — but changing the Railway value now works.
- **`validate_secret_key()` refuses to boot production on the shipped
  placeholder `SECRET_KEY`.** Production sets a real one; if boot fails on
  this, that is the reason.
- `USE_NEW_EXTRACTOR` is gone from `Settings`. The variable is still set on the
  service; `extra="ignore"` discards it. Delete it whenever.

> **Worth knowing:** typing `CORS_ORIGINS` as `list[str]` **would crash the
> service on boot** — pydantic-settings JSON-decodes a list-typed field from the
> environment before any validator runs, so a bare
> `CORS_ORIGINS=https://app.example.com` raises `SettingsError` at import. The
> field is a plain string parsed in `Settings.cors_origins`, which accepts a
> JSON array, a comma-separated list or a single origin and **never raises**.
> 15 tests cover this (`tests/test_config_aliases.py`).

### 1.6 Frontend

The saved grid no longer contains `extractTarget`. Existing templates keep
loading — the new editor derives slots from emptiness — but they lose the flag
if re-saved. **This is what dictates the deploy order.**

---

## 2. Deploy order: backend first. Not optional.

| order | outcome |
|---|---|
| **Backend → frontend** | Safe. The old editor still writes `extractTargets`; the new backend ignores them and reaches the same result |
| Frontend → backend | **Breaks extraction.** The new editor saves grids with zero `extractTarget` flags. The live backend builds `explicit_targets` from exactly that flag, and `has_explicit_targets` drives `primary_mode`. Any template saved in that window extracts wrongly |

---

## 3. What is not recoverable, and why you are not fixing it here

Run the report before you deploy, so the number in it is the number you quote
later. **Read-only. Do not pass `--apply`.**

```bash
cd backend
DATABASE_URL="<Postgres DATABASE_PUBLIC_URL>" ENVIRONMENT=development \
  .venv/Scripts/python.exe -m scripts.migrate_storage_keys
```

**Expected, as of 2026-08-24:**

```
document results            : 222
  extracted values retained : 201
  raw LLM response retained : 65
  already carrying a key    : 0
  source still on this disk : 0
  (re-run with --apply to adopt those 0)
  source unrecoverable      : 222   (never copied anywhere; s3_key stays NULL,
                                     which means 'no source retained')
```

⚠ **`source still on this disk` is counted on the machine running the script**,
not on the container. Run locally it can only ever say 0. The number that
matters is established from the database instead, and it is decisive: the most
recent production job was created **2026-07-06**, and the current container was
built **2026-08-18**. Nothing was uploaded to this container, so there is
nothing on its disk to adopt — `--apply` would have nothing to do on any
machine.

Extracted values, raw responses and exports are all intact; only the original
PDFs are gone, and they were never copied anywhere to begin with. `s3_key`
stays NULL for historical rows, where NULL now means exactly one thing: no
source document is retained for this result.

---

## 4. Pre-deploy checklist

Set once per shell:

```bash
export PROJ=8152d4bc-8029-49b2-8432-f23d13deb88b
export API=https://docagent-univer-production.up.railway.app
export WEB=https://loving-grace-production.up.railway.app
```

- [ ] **P1 — No job is mid-flight.** A deploy kills the extraction thread and
      strands the job at `processing` forever (there is no orphan recovery).

  ```bash
  railway run --service Postgres -- psql "$DATABASE_URL" -c \
    "SELECT id, client_id, status, created_at FROM extraction_jobs
     WHERE status IN ('pending','processing') ORDER BY created_at;"
  ```
  **Expect:** `(0 rows)`.
  If a row is recent, wait. If older than ~30 min it is already an orphan from
  a previous restart — ignore it, or set it to `failed`.

- [ ] **P2 — Back up the database.**

  ```bash
  railway run --service Postgres -- pg_dump "$DATABASE_URL" -Fc \
    -f docagent-preDeploy-20260824.dump
  ls -l docagent-preDeploy-20260824.dump
  ```
  **Expect:** the file exists, comfortably over 100 KB.

- [ ] **P3 — Record the rollback target.**
      Backend deployment `92b54699-a53f-4486-a636-570b4ac9df19` (commit
      `2584bb6`). Write it down; you will need it under stress.

- [ ] **P4 — Save the one CBM blob** (optional; derivable and unread).

  ```bash
  railway run --service Postgres -- psql "$DATABASE_URL" -c \
    "\copy (SELECT id, name, cell_binding_map FROM column_templates
            WHERE cell_binding_map IS NOT NULL) TO 'cbm-backup.csv' CSV HEADER"
  ```
  **Expect:** `COPY 1`.

- [ ] **P5 — Local suite is green** before you ship it.

  ```bash
  backend/.venv/Scripts/python.exe -m pytest -q
  ```
  **Expect:** `487 passed`.
  Not "178 passed, 1 xfailed" — that was the 2026-08-19 number. The `BS Luq`
  xfail is gone: `2b769e4` fixed it by declaration rather than deferring it,
  and there are **no xfails left**. `test_known_bugs.py` is now regression
  tests that must stay green, not tests that fail on purpose.

  Requires the dev dependencies, because the pyflakes gate fails rather than
  skips when the linter is absent:
  ```bash
  backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
  ```

- [ ] **P6 — Accuracy harness unchanged.** Only if you touched extraction.

  ```bash
  backend/.venv/Scripts/python.exe -m tests.harness.runner --mode replay
  backend/.venv/Scripts/python.exe -m tests.harness.runner --mode replay --no-template
  ```
  **Expect:** templated `EXTRACTION: 98.5%` / `CONTENT: 97.5%` /
  `structure FIDELITY: 100.0% (17/17)` / `INVENTED: 0.0%`; no-template
  `CONTENT: 96.7%` / `17/17` / `INVENTED: 0.0%`. The line that matters most is
  `"diff": []` in `tests/reports/latest.json` — that is the field-level
  comparison against the committed baseline.

- [ ] **P7 — Frontend type-check.**

  ```bash
  cd frontend && npm run type-check
  ```
  **Expect:** no output (tsc is silent on success).
  `npm run lint` is **not** configured in this repo — it drops into an
  interactive ESLint setup prompt. Do not put it in CI expecting a pass.

---

## 5. Deploy

### Backend

- [ ] **1 — Merge to `main`.** Both services build from `main`.

  ```bash
  git checkout main && git merge --no-ff feat/accuracy-harness && git push origin main
  git log --oneline -1 main
  ```
  **Expect:** the merge commit. Autodeploy is off, so nothing ships yet.

- [ ] **2 — Decide the storage backend.**

  Leave `STORAGE_BACKEND=local` for this deploy unless R2 is already set up.
  Everything in §1.2 works either way, and local is what production runs
  today. If you are switching to R2 in the same deploy, set the variables
  **before** step 3 — the checklist is in `docs/R2-SETUP.md`.

  ```bash
  railway variables --service docagent-univer --kv | grep -E '^(STORAGE_BACKEND|S3_|AWS_)'
  ```
  **Expect (local):** `STORAGE_BACKEND=local` and no `S3_BUCKET`.
  **Expect (R2):** `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_ENDPOINT_URL`,
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION=auto`.

- [ ] **3 — Deploy the backend service only** (`docagent-univer`), from the
      Railway dashboard or `railway up --service docagent-univer`.

  **Verify all five:**

  a. **Deployment status.**
  ```bash
  railway status
  ```
  **Expect:** the newest `docagent-univer` deployment is `SUCCESS` and its
  commit is your merge commit. With the healthcheck now taking effect, a
  container that boots but cannot answer `/health` will **not** receive
  traffic — the previous deployment keeps serving. That is your safety net.

  b. **Boot log, in order, with no traceback.**
  ```bash
  railway logs --service docagent-univer | head -40
  ```
  **Expect:**
  ```
  CORS: allowing 1 configured origin(s)          ← or the ALL-origins warning
  Starting DocAgent v2.0.0 (production)
  Database initialized
  Startup migrations: 11 applied, 0 failed
  Storage directories ready
  Schemas materialised from database: 1
  DocAgent ready.
  Uvicorn running on http://0.0.0.0:8000
  ```
  Four lines changed since the last revision and each one means something:
  - `Startup migrations: 11 applied, 0 failed` replaces the old
    `Database migrations applied`, which printed whether or not anything
    applied. **Any other count, or `N FAILED`, and the service will refuse to
    serve** (§1.1) — read the ERROR line above it, which carries the SQL.
  - `Schemas materialised from database: 1` is the 404 fix doing its job. On a
    redeploy where the disk copy survived, the line is **absent** — it only
    logs when it restored something. Absence is fine; a `Could not materialise
    schema for …` ERROR is not.
  - `CORS: allowing ALL origins…` as a **warning** means `CORS_ORIGINS` is
    unset or `*`. That is now visible rather than silent.

  c. **Health.**
  ```bash
  curl -s $API/health
  ```
  **Expect:** `{"status":"ok","version":"2.0.0","env":"production"}`

  d. **Both columns are gone.**
  ```bash
  railway run --service Postgres -- psql "$DATABASE_URL" -c \
    "SELECT column_name FROM information_schema.columns
     WHERE table_name='column_templates'
       AND column_name IN ('cell_binding_map','shape_json');"
  ```
  **Expect:** `(0 rows)`.

  e. **The schema is on disk where the engine looks for it.** This is the
     single check that proves the 404 bug is fixed, and it is the one the old
     runbook could not have had.
  ```bash
  railway run --service Postgres -- psql "$DATABASE_URL" -c \
    "SELECT client_id, length(yaml_content) FROM client_schemas;"
  ```
  **Expect:** `demo_001 | 7391`. Then confirm an upload gets past the schema
  lookup rather than 404ing — step 5 below is that test.

- [ ] **4 — Templates load and carry a shape.** The best single signal that
      fresh shape computation works against real data.

  ```bash
  TOKEN=$(curl -s -X POST $API/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"<you>","password":"<pw>"}' \
    | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

  curl -s $API/api/templates -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json; t=json.load(sys.stdin); print(len(t),'templates'); print(sum(1 for x in t if x.get('shape')),'with a shape'); print([x['name'] for x in t if not x.get('shape')])"
  ```
  **Expect:** `19 templates`, `19 with a shape`, and an empty list.

- [ ] **5 — Extract one document WITH a template.** Use **`Bank-Statement-101`
      (id 29)** — its line-item table was previously invisible, so this is the
      sharpest single test of the band fix, and the upload also proves the
      schema lookup no longer 404s.

  Upload a bank statement through the UI or the API, wait for the job, download
  the `.xlsx`.

  **Expect:**
  - the upload returns **202**, not `404 "No schema found."`;
  - the job reaches **`completed`** — not `partial`, not `failed`;
  - `successful` equals the number of files, `failed` is `0`;
  - the sheet has the header fields **and a transaction table with rows**.

  If the job says `failed` or `partial`, open the job: every failed document
  now carries its own error message. That is the new diagnostic path — use it
  before rolling back.

- [ ] **6 — Extract one document with NO template.**

  ```bash
  curl -s $API/api/jobs/<job_id>/inferred-templates -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json;d=json.load(sys.stdin);print(len(d),'shape(s)');print(d[0]['template']['name'] if d else '')"
  ```
  **Expect:** at least one entry, with a `template` payload and a real name.
  The downloaded sheet should have proper column headings, not a single column.

- [ ] **7 — Re-download one historical job** (anything before today).
      **Expect:** downloads without a 500 and looks as it did. 22 of 22
      historical documents were verified locally, so this is a spot check.

### Frontend

- [ ] **8 — Deploy `loving-grace`.** Only after step 3 verified.

  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" $WEB/health
  curl -s -o /dev/null -w "%{http_code}\n" $WEB/login
  ```
  **Expect:** `200` for both. Then log in; the Templates page lists all 19.

- [ ] **9 — Open a template and save it unchanged.** This is the step that
      strips `extractTarget`, so it is the real test of the export fix.
      **Do it on `Cheque-101` (id 13) first**, not `Invoice-Template-101`.

  **Expect:** the save returns immediately. Template save no longer makes a
  Gemini call, so if it hangs for seconds something is wrong. Then extract with
  that template and confirm the download still has values in the value column.

### After

- [ ] **10** — Delete the inert `USE_NEW_EXTRACTOR` variable (optional).
- [ ] **11** — Set `CORS_ORIGINS` to `https://loving-grace-production.up.railway.app`
      if you want the API closed to other origins. It is read now; before this
      deploy it was ignored.
  ```bash
  curl -si $API/health -H 'Origin: https://evil.example.com' | grep -i access-control-allow-origin
  ```
  **Expect after setting it:** the header is the frontend URL, **not** `*`.

---

## 6. Rollback

**Trigger it if:** the boot log shows a traceback or `N FAILED` migrations;
`/health` does not return 200; `GET /api/templates` 500s; step 5 produces a
sheet with no table rows; or step 5 uploads answer `404 "No schema found."`.

With the healthcheck in place, a deploy that never becomes healthy will not
take traffic at all — the previous deployment keeps serving and you can simply
stop. The steps below are for a deploy that went healthy and then proved wrong.

1. **Redeploy `92b54699`** (commit `2584bb6`) from the Railway deployments list
   for `docagent-univer`.

2. **Verify the column came back.** The old code re-creates it during boot,
   before serving:
   ```bash
   railway logs --service docagent-univer | head -20
   curl -s $API/health
   railway run --service Postgres -- psql "$DATABASE_URL" -c \
     "SELECT column_name FROM information_schema.columns
      WHERE table_name='column_templates' AND column_name='cell_binding_map';"
   ```
   **Expect:** `Database migrations applied` in the log (the old wording — that
   is how you know you are on the old code), `/health` 200, and **one row**.
   If the column is missing, run it by hand and restart:
   ```bash
   railway run --service Postgres -- psql "$DATABASE_URL" -c \
     "ALTER TABLE column_templates ADD COLUMN IF NOT EXISTS cell_binding_map TEXT;"
   ```

3. **If you switched `STORAGE_BACKEND` to `s3`, set it back to `local`.**
   `2584bb6` has no storage abstraction and will ignore the S3 variables, but
   leaving them set is confusing. Files written to R2 during the window stay in
   R2; nothing reads them on the old code. Do not delete the bucket — you will
   want those objects when you roll forward again.

4. **Rolling back re-opens the schema 404.** `2584bb6` has no
   `_materialise_schemas`, so the moment its container restarts, every upload
   answers `404 "No schema found."` again. If you need uploads working while
   rolled back, re-upload the client schema through the UI, or write the file
   into the container's `./storage/schemas/clients/` — it will not survive the
   next restart either. **This is the strongest argument for rolling forward
   with a fix rather than back.**

5. **If the frontend was already deployed, roll it back too.** A new frontend
   against an old backend is the unsafe combination (§2).

6. **Only if the database is inconsistent** — it should not be, nothing is
   written or migrated:
   ```bash
   railway run --service Postgres -- pg_restore -d "$DATABASE_URL" \
     --clean --if-exists docagent-preDeploy-20260824.dump
   ```

**The one thing rollback does not undo:** a template saved through the new
editor between deploy and rollback has lost its `extractTarget` flags. Under
the old code it routes by `explicit_targets` and will extract incorrectly until
re-marked. That is why step 9 is last and scoped to a template you can afford
to re-save.

---

## 7. Known-unfixed, for the record

Verified present in the code being deployed. None is introduced by it.

| # | issue | client impact |
|---|---|---|
| 1 | **Image uploads have no OCR.** Sent to Gemini Vision with no text layer; grounding cannot run, so every value is `unverified` and `needs_review` is always set | A photographed document extracts unverified. The one path that never joined the single pipeline |
| 2 | **A "Drive" tab leads nowhere.** `GoogleDriveConnector.authenticate()` uses a desktop OAuth flow that cannot complete in a container — and `drive.py:220` calls the worker with 4 of its 8 required arguments, raising `TypeError` before any work starts. Pinned by `tests/test_drive_worker_contract.py` so it cannot change shape quietly | Visible dead functionality in a demo. Fails cleanly |
| 3 | **Cancel does not cancel.** No cancellation check in the loop | Cancelling a batch relabels it briefly; work and spend continue |
| 4 | **Jobs strand at `processing`.** Daemon thread, no startup orphan scan | Any restart mid-batch leaves the UI polling forever. Hence P1 |
| 5 | Template access is not ownership-checked on upload | Cross-tenant template use |
| 6 | Passwords are single-round salted SHA-256; a password change does not invalidate issued JWTs | A security review will ask |
| 7 | **`BS Luq` (id 31)** — headers at columns 0 and 2 with a gap. Now fixable by declaring the region in the editor rather than restructuring the template | Was an xfail; no longer |
| 8 | **`Bank-Statement-101` (id 29)** has four column headings and **no Credit or Balance column** | Those values have nowhere to go. Template-side, not engine |
| 9 | **No source document is retained for the 222 historical results** (§3) | "Download original" cannot be offered for anything before this deploy |

`PRIMARY_LLM` now defaults to `gemini` in code (it used to default to the
non-functional `groq`), so a fresh checkout works. That item is resolved.

---

## 8. `PRIMARY_LLM`, and what a mid-batch rate limit does

### It must be `gemini`

Production sets it, and it must stay. All three configured Groq models are
decommissioned and the account is offered no vision-capable model, so
`PRIMARY_LLM=groq` is a completely non-functional configuration.

The practical consequence: **there is no fallback provider.**
`LLMRouter.extract` tries primary then fallback; with Gemini primary the
fallback is Groq, which always fails, and the router returns `"All providers
failed for extraction"`. The redundancy the code advertises does not exist —
Gemini is an unacknowledged single point of failure. Worth knowing before you
tell a client there is failover.

### If Gemini rate-limits mid-batch, today

Traced through the code rather than assumed:

1. `_llm_json` retries **3 times**, backing off **1 s, then 2 s** on a
   429/quota error. Total tolerated delay ≈ **3 seconds**.
2. If all three fail, the slot extractor **fails that one document** with
   `"Slot extraction returned no usable JSON"`.
3. **The batch continues.** `failed += 1`, a 2 s inter-document delay, next
   document.
4. The job ends — and this is the part that changed — as **`partial`** if
   anything succeeded, or **`failed`** if nothing did. It no longer reports
   `completed`. Every failed document carries its own error message.

Two things still follow, and both matter:

- **3 seconds of backoff is far too short for a real rate limit.** Gemini quota
  windows are per-minute; a sustained 429 will not clear in 3 s. In practice
  the limit is hit, ~5 s is burned per document, and **every remaining document
  in the batch fails in sequence** — the batch drains fast rather than waiting
  it out.
- **A rate-limited batch is now at least honestly labelled.** It reports
  `partial` or `failed` with per-document errors instead of `completed`.
  Nobody is alerted, but the job no longer lies about what it produced.

If you want this to behave, the fix is to treat a 429 differently from a parse
failure: back off in the tens of seconds, and pause the whole batch rather than
burning through the remaining documents. That is a change, not a config
setting, and it is not in this deploy.
