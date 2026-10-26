# Release checklist — before the first push

## 1. One command

```
backend\.venv\Scripts\python.exe scripts\prepush_check.py          # everything (~25 min)
backend\.venv\Scripts\python.exe scripts\prepush_check.py --quick  # repository checks only
```

Read-only on the working tree: the suite, the native readings and both
harness modes run in a clean `git archive HEAD` export in a temporary
directory; the frontend checks run in `frontend/` and write only its ignored
build output. It exits non-zero with a list whenever anything below is not
satisfied. Secrets are reported by path, line and type, never by value.

| Check | Passes when |
|---|---|
| working tree clean | `git status --porcelain` is empty |
| secret scan | no tracked file matches a key pattern (AWS, Google, Groq, OpenAI-style, xAI, GitHub, Slack, private key, JWT, a database URL with a password for a non-local host) |
| machine-specific paths | no Windows profile path, POSIX home path, Git-Bash drive path or local repo path in a tracked file (`tests/llm_cache/` excluded: recorded model traffic) |
| `.env` files | none tracked except `*.example` |
| license | a `LICENSE` file exists — **MANUAL** until one is chosen |
| file size | no tracked file over 5 MB |
| removed provider | "Groq", "Grok" or "xAI" appears only in history docs (`DEPLOY-RUNBOOK`, `ROADMAP`, `SECURITY`, this file, `design-history/`, `DECISION-LOG`) and the test that pins its absence |
| links | every relative link in `README.md` and `docs/**/*.md` resolves |
| CI | every `.github/workflows/*.yml` parses and has `jobs` |
| settings documented | every field of `backend/app/config.py::Settings` is named in `docs/OPERATIONS.md` |
| suite | `pytest` passes in the clean export |
| native readings | `python -m tests.harness.native_hashes --check` matches `tests/reports/native_hashes.json` (69 PDFs) |
| harness | replay, templated EXPORT = 97.2% and no-template EXPORT = 96.7% (`tests/reports/release_baseline.json`) |
| frontend | `npm run type-check`, `npm test`, `npm run build` |

A changed baseline is a decision, not a fix: update `native_hashes.json` or
`release_baseline.json` only in a commit that says why the reading or the
number moved.

## 2. Manual — only Tauseef can do these

The script lists them as MANUAL and fails until run with `--manual-done`.

1. **Revoke the leaked Groq key.** Commit `ecaead9` (2026-04-26, on `main` and
   `origin/main`) has a Groq API key in `.env.example`. History is not
   rewritten; revoke the key at the provider so the copy in history is dead.
2. **Railway variables.** Delete `GROQ_API_KEY`, `GROQ_CLASSIFICATION_MODEL`,
   `GROQ_EXTRACTION_MODEL`, `GROQ_VISION_MODEL` (no longer read); if
   `PRIMARY_LLM` says `groq`, set it to `gemini` or remove it.
3. **`DEMO_CLIENT_IDS`.** Check it names only the demo tenant: every tenant in
   it gets demo limits and the sample-document folder.
4. **License.** Choose one and add `LICENSE`; until then the code is not
   licensed to anyone.
5. **Third-party sample PDFs.** `tests/test_pdfs/round2/` holds public samples
   (CFPB forms, a bank's sample statement, a utility's sample bill, a press
   release). Check their terms allow redistribution in a public repository,
   or keep the repository private, or remove them (the 69-PDF measurements
   would then change and the baselines need a recorded update).
6. **Staging.** Set up the staging environment in `docs/CLIENT-TRIAL.md` §1
   (any family; `docs/CHEQUE-TRIAL.md` is the cheque example) before any real
   document is uploaded, and run `scripts/smoke_test.py --base-url` against it.
7. **Roles.** Decide whether to make `platform_admin` an explicit stored role
   (a data migration) — `docs/proposals/roles.md`. (Owner hard-delete was
   decided in round 14: the job's own user may delete it, with confirmation.)
8. **VERIFY items.** Confirm each one in `docs/OPERATIONS.md` and
   `docs/CLIENT-DATA-FAQ.md`; the FAQ is not shown to a client before.
9. **Drive and the proxy.** Set `DRIVE_TENANT` if Google Drive is used (off
   by default since round 14); confirm Railway appends the client address as
   the last `X-Forwarded-For` entry (the login limiter relies on it; set
   `TRUSTED_PROXY_COUNT` if another proxy sits in front).
10. **Firm ids.** Run `scripts/check_firm_ids.py` on every production firm id
    before the first deploy of this release; every line must say `ok`
    ([OPERATIONS.md](OPERATIONS.md) §12).

New in round 14 (no migration): routes `POST/GET /api/admin/tenants`,
`POST /api/admin/tenants/{id}/deactivate|activate`, `POST
/api/auth/change-password`, `GET /api/usage`; `DELETE /api/jobs/{id}/data`
now needs `?confirm=true`; script `scripts/create_tenant.py`; variables
`TENANT_MONTHLY_PAGE_LIMIT`, `DATA_RETENTION_DAYS`, `DRIVE_TENANT` (all off by
default).

New in Run 15 (no migration): `TRUSTED_PROXY_COUNT` (default 1), the OCR
deadlines `OCR_PROBE_TIMEOUT_S`, `OCR_RENDER_TIMEOUT_S`,
`OCR_TESSERACT_TIMEOUT_S`, `OCR_PAGE_TIMEOUT_S`, `OCR_POOL_TIMEOUT_S`
(OPERATIONS §11); script `scripts/check_firm_ids.py`; review marks answer 409
on a conflict that never clears; page routes answer 413 for an image over
`MAX_IMAGE_PIXELS` and 503 when the renderer times out.

## 3. After the push

Railway (backend) and Vercel (frontend) deploy from `main`; follow
`docs/DEPLOY-RUNBOOK.md` and confirm the commit SHA is on GitHub.

New in Runs 16-20 (no migration): `ENVIRONMENT=staging|production` now
REFUSES to start on a short or placeholder `SECRET_KEY` (< 32 characters),
SQLite or localhost `DATABASE_URL`, incomplete s3 settings, a missing
`GEMINI_API_KEY`, open CORS, or `TRUSTED_PROXY_COUNT` outside 0–5 —
**check the live variables against docs/ENVIRONMENTS.md before deploying**;
`GRACEFUL_SHUTDOWN_SECONDS` (60), `LOG_FORMAT` (`text`|`json`); routes
`GET /ready` (set it as the Railway health check), `GET /api/jobs/{id}/charts`,
`POST /api/extract/page-count`; the backend image runs as UID 10001 under
tini (`scripts/verify_image.sh`); Next.js 15.5 / React 19, FastAPI 0.129.
After the deploy: `python scripts/smoke_test.py --base-url <url>`.

## Demo acceptance (Part A9)

Before showing the product to a client, run the whole demo flow offline
(`scripts/e2e/README.md`): `scripts/e2e/stack.py` (stub model, throwaway
database), then `frontend/e2e/run.sh`. `demo-acceptance.spec.cjs` fails on
any broken step — sign in, draw a template, upload a two-invoice file with
every option on (it must come back as two documents), edit a value, mark the
document reviewed, export, and a second firm getting 404 for the job — and
the other specs cover the editor's keyboard, the options panel and every
page at laptop and tablet width. All must pass.
