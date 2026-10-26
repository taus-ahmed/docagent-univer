# Environments — every variable, per environment

`ENVIRONMENT` selects how strict the backend is at start (Part 2.4,
`app/config.py::_validate_for_environment`):

| `ENVIRONMENT` | Strictness |
|---|---|
| `development` (alias `dev`) | nothing refused: a fresh checkout runs on the defaults |
| `staging` | every rule below; the backend **refuses to start** and lists every problem, naming the setting and never its value |
| `production` | as staging, plus local storage is warned about and the API docs are hidden |

**S** = secret (never in chat, tickets or code). "Required" = refused at start
in staging and production when missing or weak.

| Variable | development | staging | production | Notes |
|---|---|---|---|---|
| `ENVIRONMENT` | `development` | `staging` | `production` | |
| `SECRET_KEY` **S** | default | required, ≥ 32 chars | required, ≥ 32 chars | `openssl rand -hex 32`; changing it signs everyone out |
| `DATABASE_URL` **S** | local Postgres or SQLite | required, PostgreSQL, not localhost | same | Railway provides it |
| `GEMINI_API_KEY` **S** | empty (stub or no calls) | required when `PRIMARY_LLM=gemini` | same | |
| `PRIMARY_LLM` / `LLM_FALLBACKS` | `gemini` or `stub` | `gemini`; `stub` refused | `gemini`; `stub` refused | [OFFLINE-DEMO.md](OFFLINE-DEMO.md) |
| `ALLOWED_ORIGINS` (or `CORS_ORIGINS`) | empty = any | required, explicit, no `*` | same | the frontend's origin(s) |
| `TRUSTED_PROXY_COUNT` | `1` | 0–5 | 0–5 (Railway: `1`) | [OPERATIONS.md](OPERATIONS.md) §9 |
| `STORAGE_BACKEND` | `local` | `s3` recommended | `s3` (local warned: files lost at deploy) | |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `AWS_REGION` | — | required with `s3` (bucket) | same | [R2-SETUP.md](R2-SETUP.md) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` **S** | — | required with `s3` | same | |
| `GRACEFUL_SHUTDOWN_SECONDS` | `60` | `60` | `60`, below the platform's stop timeout | |
| `LOG_FORMAT` | `text` | `json` recommended | `json` recommended | [OPERATIONS.md](OPERATIONS.md) §5 |
| `OPTION_MAX_CALLS_PER_JOB` | `20` | `20` | `20` | |
| `MAX_UPLOAD_SIZE_MB` (alias `MAX_FILE_SIZE_MB`) | `50` | `50` | `50` | per file. A refusal names the file, its size, the limit and this setting |
| `MAX_PDF_PAGES` | `200` | `200` | `200` | per PDF; the refusal states the file's page count. Raise only with a recorded reason (memory: [OPERATIONS.md](OPERATIONS.md) §11) |
| `MAX_IMAGE_PIXELS` | `50000000` | `50000000` | `50000000` | per image (≈ A4 at 600 dpi is 35 M); the refusal states the image's pixel count |
| `TENANT_MONTHLY_PAGE_LIMIT`, `DATA_RETENTION_DAYS`, `DRIVE_TENANT` | off | as agreed | as agreed | |
| `OCR_*` deadlines, `OCR_WORKERS`, `OCR_MEMORY_LIMIT_MB` | defaults | defaults | defaults (memory guard `3072`, below the container's memory) | [OPERATIONS.md](OPERATIONS.md) §11 |
| `DOCAGENT_BOOTSTRAP_ADMIN_*` **S** | optional | first boot only | first boot only, then remove the password | |
| `NEXT_PUBLIC_API_URL` (frontend) | `http://localhost:8000` | staging backend URL | production backend URL | build-time |
| `BACKEND_URL` (frontend server) | `http://localhost:8000` | staging backend URL | production backend URL | used by the Next.js proxy route |

Every other setting has a safe default; the full list with examples is in
[OPERATIONS.md](OPERATIONS.md) §2 (`scripts/prepush_check.py` checks every
setting is named there).

## Platform settings (the repository has no Railway or Vercel config files)

`railway.json` holds only its schema line, so these are set in the dashboards:

| Service | Setting | Value |
|---|---|---|
| Railway backend | Dockerfile path | `Dockerfile.backend` (build context: repository root) |
| Railway backend | Start command | none: the image's `ENTRYPOINT` (tini → `backend/docker-entrypoint.sh` → uvicorn on `$PORT`) |
| Railway backend | Health check path | `/ready` (readiness); `/health` is liveness only |
| Railway backend | Health check timeout | 120 s |
| Railway backend | Stop/drain timeout | above `GRACEFUL_SHUTDOWN_SECONDS` |
| Vercel frontend | Root directory | `frontend` |
| Vercel frontend | Build command | `npm run build` |
| Vercel frontend | Install command | `npm ci` |
| Vercel frontend | Output | Next.js default |

After building the backend image: `sh scripts/verify_image.sh docagent-backend`
(versions, UID 10001, storage writable, Tesseract eng+osd, pdftoppm, tini as
PID 1, `/health` and `/ready`, stop on SIGTERM).
