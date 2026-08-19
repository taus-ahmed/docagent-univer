# Deploy runbook — `feat/accuracy-harness` → Railway production

Prepared 2026-08-19. **Nothing has been deployed.** Every fact was read from the
live Railway project or the production database read-only, or from the code.

Work top to bottom. Do not start a step until the previous one verified.

---

## 0. Facts you need before you start

| | |
|---|---|
| Live backend deployment | `92b54699-a53f-4486-a636-570b4ac9df19`, commit **`2584bb6`** |
| Live frontend deployment | service `loving-grace`, branch `main` |
| **`cad3329` is NOT live** | it was deployed 2026-07-05 and set `REMOVED` on 2026-08-17 |
| Deploy diff | exactly the commits on `feat/accuracy-harness` — `2584bb6` is its merge-base, so no unrelated drift |
| Both services build from | branch **`main`** — nothing ships until you merge |
| Autodeploy | off, as you set it |
| Healthcheck | **now configured** — see §1.3. Railway will hold traffic on the old deployment if the new one fails to answer `/health` |

Project `8152d4bc-8029-49b2-8432-f23d13deb88b`, environment `production`.
Backend service `1f378431-2df2-4e45-ba41-1297cc2d532d` (`docagent-univer`).
Frontend service `33271ebb-6a2a-4acf-a7e4-c6311c64ee4c` (`loving-grace`).

---

## 1. What changes

### 1.1 Database

| change | reversible? |
|---|---|
| `column_templates.cell_binding_map` **DROPPED** | **Yes** — `2584bb6` re-creates it on boot. See §5 |
| `column_templates.shape_json` `DROP IF EXISTS` | **No-op** — verified absent in production; it never shipped |

Nothing added, renamed or migrated. The one row holding a `cell_binding_map` is
template id 24 (`Invoice-Template-101`); its content is derivable from that
template's unchanged grid.

Each ALTER is individually wrapped in `try/except` with a rollback, so a failed
migration logs at DEBUG and boot continues. It cannot stop the service starting.

### 1.2 API — additive only

- `GET /api/jobs/{id}/inferred-templates` added (auth-gated).
- `TemplateResponse.shape` added, `Optional[dict] = None`.
- No route removed, no path or method altered (verified by diffing the route
  decorator sets on `extract.py` and `templates.py`).

### 1.3 Config and healthcheck (new in this revision)

- **`/health` is now the healthcheck for both services**, set in code at
  `railway.json` (`deploy.healthcheckPath`, `healthcheckTimeout: 120`).
  Railway reads `railway.json` from the repo root for each service, and
  **config defined in code overrides the dashboard**. Only `deploy.*` is set,
  so each service keeps its own dashboard `dockerfilePath`.
  The frontend previously had no health endpoint; `frontend/app/health/route.ts`
  adds one that answers 200 without touching the backend — a healthcheck that
  depended on another service would turn that service's outage into a failed
  deploy here.
  **Dashboard equivalent, if you prefer to set it there:** service →
  **Settings → Deploy → Healthcheck Path** → `/health`. Note the file wins over
  the dashboard, so setting both is harmless but the file is authoritative.
- **CORS now reads configuration.** `allow_origins` came from a hardcoded
  `["*"]`; it now comes from `settings.cors_origins`, which accepts either
  `CORS_ORIGINS` (what production sets) or `ALLOWED_ORIGINS` (what the code
  declared). `allow_credentials` stays `False` — the frontend authenticates
  with a Bearer token from `localStorage`, not a cookie, so turning it on would
  be a behaviour change rather than a fix.
- **`MAX_FILE_SIZE_MB` is now read.** It aliases to `MAX_UPLOAD_SIZE_MB`.
  Both were 50, so there is no behaviour change today — but changing the
  Railway value will now actually change the limit.
- `USE_NEW_EXTRACTOR` is gone from `Settings`. The variable is still set on the
  service; `extra="ignore"` discards it, so it cannot raise. Delete it whenever.

> **Worth knowing:** the obvious version of the CORS fix — typing the field as
> `list[str]` — **would have crashed the service on boot.** pydantic-settings
> JSON-decodes a list-typed field straight from the environment before any
> validator runs, so `CORS_ORIGINS=https://app.example.com` raises
> `SettingsError` at import. The field is therefore a plain string, parsed in
> `Settings.cors_origins`, which accepts a JSON array, a comma-separated list or
> a single origin and **never raises** — a malformed value falls back to `["*"]`
> rather than stopping the service. 15 tests cover this
> (`tests/test_config_aliases.py`).

### 1.4 Removed: the debug dump that wrote customer content to disk

`_dump_raw_extraction` is deleted from `engine/connectors/llm_router.py`. It ran
on **every successful extraction**, writing the model's full response and 1,500
characters of prompt — both containing document content — to a single fixed
filename with no retention policy, from code commented "TEMPORARY DEBUG".

**Audited the whole backend for anything else writing document content outside
the intended storage path. There is nothing.** Every other write is either an
in-memory buffer (`BytesIO` for Excel and images), the intended storage path
(`storage.py` uploads/outputs/schemas), a Google Drive OAuth token, or the
orphaned CLI-only engine writers.

### 1.5 Frontend

The saved grid no longer contains `extractTarget`. Existing templates keep
loading — the new editor derives slots from emptiness and ignores the old flag —
but they lose it if re-saved. **This is what dictates the deploy order.**

---

## 2. Deploy order: backend first. Not optional.

| order | outcome |
|---|---|
| **Backend → frontend** | Safe. The old editor still writes `extractTargets`; the new backend ignores them and reaches the same result. |
| Frontend → backend | **Breaks extraction.** The new editor saves grids with zero `extractTarget` flags. The live backend builds `explicit_targets` from exactly that flag (`extract.py:443/463`, 40 references), and `has_explicit_targets` drives `primary_mode`. Any template saved in that window extracts wrongly. |

---

## 3. Pre-deploy checklist

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
  If a row is recent, wait. If older than ~30 min it is already an orphan from a
  previous restart — ignore it, or set it to `failed`.

- [ ] **P2 — Back up the database.**

  ```bash
  railway run --service Postgres -- pg_dump "$DATABASE_URL" -Fc \
    -f docagent-preDeploy-20260819.dump
  ```
  **Expect:** the file exists, comfortably over 100 KB.
  ```bash
  ls -l docagent-preDeploy-20260819.dump
  ```

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
  **Expect:** `178 passed, 1 xfailed`. The xfail is `BS Luq`, deliberate.

---

## 4. Deploy

### Backend

- [ ] **1 — Merge to `main`.** Both services build from `main`.

  ```bash
  git checkout main && git merge --no-ff feat/accuracy-harness && git push origin main
  ```
  **Expect:** `git log --oneline -1 main` shows the merge commit.
  Autodeploy is off, so nothing ships yet.

- [ ] **2 — Deploy the backend service only** (`docagent-univer`) from the
      Railway dashboard or `railway up --service docagent-univer`.

  **Verify all four:**

  a. Deployment status.
  ```bash
  railway status
  ```
  **Expect:** the newest `docagent-univer` deployment is `SUCCESS`, and its
  commit is your merge commit. With the healthcheck now set, a container that
  boots but cannot answer `/health` will **not** receive traffic — the previous
  deployment keeps serving. That is your safety net.

  b. Boot log, in order, **with no traceback**.
  ```bash
  railway logs --service docagent-univer | head -40
  ```
  **Expect:**
  ```
  Starting DocAgent v2.0.0 (production)
  Database initialized
  Database migrations applied
  Storage directories ready
  DocAgent ready.
  Uvicorn running on http://0.0.0.0:8000
  ```
  **Also expect one CORS line.** If `CORS_ORIGINS` is a real origin you will see
  `CORS: allowing N configured origin(s)`. If it is unset or `*` you will see the
  warning `CORS: allowing ALL origins…` — which tells you the variable is not
  doing what you think, and is now visible instead of silent.

  c. Health.
  ```bash
  curl -s $API/health
  ```
  **Expect:** `{"status":"ok","version":"2.0.0","env":"production"}`

  d. Both columns are gone.
  ```bash
  railway run --service Postgres -- psql "$DATABASE_URL" -c \
    "SELECT column_name FROM information_schema.columns
     WHERE table_name='column_templates'
       AND column_name IN ('cell_binding_map','shape_json');"
  ```
  **Expect:** `(0 rows)`.

- [ ] **3 — Templates load and now carry a shape.** This is the single best
      signal that fresh shape computation works against real data.

  ```bash
  TOKEN=$(curl -s -X POST $API/api/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"<you>","password":"<pw>"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

  curl -s $API/api/templates -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json; t=json.load(sys.stdin); print(len(t),'templates'); print(sum(1 for x in t if x.get('shape')),'with a shape'); print([x['name'] for x in t if not x.get('shape')])"
  ```
  **Expect:** `19 templates`, `19 with a shape`, and an empty list.

- [ ] **4 — Extract one document WITH a template.** Use **`Bank-Statement-101`
      (id 29)** — its line-item table was previously invisible, so this is the
      sharpest single test of the band fix.

  Upload a bank statement through the UI or the API, wait for the job, download
  the .xlsx.
  **Expect:** the sheet has the header fields **and a transaction table with
  rows**. If it has header fields and no rows, the band fix did not take
  effect → roll back (§5).

- [ ] **5 — Extract one document with NO template.**

  ```bash
  curl -s $API/api/jobs/<job_id>/inferred-templates -H "Authorization: Bearer $TOKEN" \
    | python -c "import sys,json;d=json.load(sys.stdin);print(len(d),'shape(s)');print(d[0]['template']['name'] if d else '')"
  ```
  **Expect:** at least one entry, with a `template` payload and a real name.
  The downloaded sheet should have proper column headings, not a single column.

- [ ] **6 — Re-download one historical job** (anything from before today).
      **Expect:** downloads without a 500 and looks as it did. 22 of 22 historical
      documents were verified locally, so this is a spot check.

### Frontend

- [ ] **7 — Deploy `loving-grace`.** Only after step 2 verified.

  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" $WEB/health
  curl -s -o /dev/null -w "%{http_code}\n" $WEB/login
  ```
  **Expect:** `200` for both. Then log in; the Templates page lists all 19.

- [ ] **8 — Open a template and save it unchanged.** This is the step that
      strips `extractTarget`, so it is the real test of the export fix.
      **Do it on `Cheque-101` (id 13) first**, not `Invoice-Template-101`.

  **Expect:** the save returns immediately. Template save no longer makes a
  Gemini call, so if it hangs for seconds something is wrong. Then extract with
  that template and confirm the download still has values in the value column.

### After

- [ ] **9** — Delete the inert `USE_NEW_EXTRACTOR` variable from the backend
      service (optional).
- [ ] **10** — Set `CORS_ORIGINS` to `https://loving-grace-production.up.railway.app`
      if you want the API closed to other origins. It is read now; before this
      deploy it was ignored. Verify:
  ```bash
  curl -si $API/health -H 'Origin: https://evil.example.com' | grep -i access-control-allow-origin
  ```
  **Expect after setting it:** the header is the frontend URL, **not** `*`.

---

## 5. Rollback

**Trigger it if:** the boot log shows a traceback; `/health` does not return
200; `GET /api/templates` 500s; or step 4 produces a sheet with no table rows.

With the healthcheck in place, a deploy that never becomes healthy will not take
traffic at all — the previous deployment keeps serving and you can simply stop.
The steps below are for a deploy that went healthy and then proved wrong.

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
   **Expect:** `Database migrations applied` in the log, `/health` 200, and
   **one row** from the query.
   If the column is missing, run it by hand and restart:
   ```bash
   railway run --service Postgres -- psql "$DATABASE_URL" -c \
     "ALTER TABLE column_templates ADD COLUMN IF NOT EXISTS cell_binding_map TEXT;"
   ```

3. **If the frontend was already deployed, roll it back too.** A new frontend
   against an old backend is the unsafe combination (§2).

4. **Only if the database is inconsistent** — it should not be, nothing is
   written or migrated:
   ```bash
   railway run --service Postgres -- pg_restore -d "$DATABASE_URL" \
     --clean --if-exists docagent-preDeploy-20260819.dump
   ```

**The one thing rollback does not undo:** a template saved through the new
editor between deploy and rollback has lost its `extractTarget` flags. Under the
old code it routes by `explicit_targets` and will extract incorrectly until
re-marked. That is why step 8 is last and scoped to a template you can afford to
re-save.

---

## 6. Known-unfixed, for the record

Verified present in the code being deployed. None is introduced by it.

| # | issue | client impact |
|---|---|---|
| 1 | **Image uploads have no OCR.** Sent straight to Gemini Vision with no text layer; grounding cannot run, so every confidence is forced `medium` and `needs_review` is always set. | A photographed document extracts unverified. The one path that never joined the single pipeline. |
| 2 | **A "Drive" tab leads nowhere.** `GoogleDriveConnector.authenticate()` uses a desktop OAuth flow that cannot complete in a container. | Visible dead functionality in a demo. Fails cleanly (400/401). |
| 3 | **Cancel does not cancel.** No cancellation check in the loop; the thread sets `completed` at the end regardless. | Cancelling a batch relabels it briefly; work and spend continue. |
| 4 | **Jobs strand at `processing`.** Daemon thread, no startup orphan scan. | Any restart mid-batch leaves the UI polling forever. Hence step P1. |
| 5 | Template access is not ownership-checked on upload (`POST /api/extract/upload` loads a template by id with no `client_id` check). | Cross-tenant template use. |
| 6 | Passwords are single-round salted SHA-256; a password change does not invalidate issued JWTs (only deactivating the user does). | A security review will ask. |
| 7 | `PRIMARY_LLM` still defaults to `"groq"` in code, which is non-functional (see §7). Production overrides it. | Anyone running the repo fresh gets an app that cannot extract. |
| 8 | **`BS Luq` (id 31)** cannot extract its liabilities sections — headers at columns 0 and 2 with a gap. You are restructuring the template. | Two sections missing from that one sheet. |
| 9 | **`Bank-Statement-101` (id 29)** has only four column headings and **no Credit or Balance column**. | Those values have nowhere to go. Template-side, not engine. |

---

## 7. `PRIMARY_LLM`, and what a mid-batch rate limit does

### It must be `gemini`

Production already sets it, and it must stay. All three configured Groq models
(`llama-3.2-11b-vision-preview`, `llama-3.3-70b-versatile`,
`llama-3.2-90b-vision-preview`) are decommissioned, and the account is offered
no vision-capable model at all — so `PRIMARY_LLM=groq` is a completely
non-functional configuration.

The practical consequence: **there is no fallback provider.** `LLMRouter.extract`
tries primary then fallback; with Gemini primary the fallback is Groq, which
always fails, and the router returns `"All providers failed for extraction"`.
The redundancy the code advertises does not exist — Gemini is an unacknowledged
single point of failure. Worth knowing before you tell a client there is
failover.

The code default (`config.py`) is still `"groq"`. I did not change it, because
you asked for two specific config fixes and that would have been a third. It is
a one-line change whenever you want it.

### If Gemini rate-limits mid-batch, today

Traced through the code rather than assumed:

1. `_llm_json` retries **3 times**. On a 429 / rate-limit / quota error it backs
   off exponentially: **1s, then 2s** (the cap of 30s is never reached in 3
   attempts). Total tolerated delay ≈ **3 seconds**.
2. If all three fail, the slot extractor **fails that one document** with
   `"Slot extraction returned no usable JSON"`.
3. **The batch continues.** `failed += 1`, a 2s inter-document delay, next
   document. It does not abort.
4. The job ends as **`status="completed"`** with a non-zero `failed` count.

Two things follow, and both matter:

- **3 seconds of backoff is far too short for a real rate limit.** Gemini quota
  windows are per-minute; a sustained 429 will not clear in 3s. So in practice
  the limit is hit, ~5s is burned per document, and **every remaining document
  in the batch fails in sequence** — the batch drains fast rather than waiting
  it out.
- **A rate-limited batch looks like a successful job.** The status is
  `completed`, not `failed`; the only signal is `failed > 0` on the job row and
  per-document error messages. Nobody is alerted.

If you want this to behave, the fix is to treat a 429 differently from a parse
failure: back off in the tens of seconds, and pause the whole batch rather than
burning through the remaining documents. That is a change, not a config setting,
and it is not in this deploy.
