# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

DocAgent v2.0 is a multi-tenant AI-powered document extraction SaaS. PDFs are uploaded, classified by type, images sent to Gemini Vision API or Groq vision, extracted data cross-validated by pdfplumber, and results exported as Excel. Multi-tenant with `client_id` isolation on every data table, JWT auth, PostgreSQL.

**Production URL**: `https://loving-grace-production.up.railway.app`

---

## Commands

### Backend
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
# copy .env.example .env and fill in DATABASE_URL, GROQ_API_KEY, GEMINI_API_KEY, SECRET_KEY
alembic upgrade head          # run DB migrations (only needed on first setup)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```powershell
cd frontend
npm install
# create .env.local with: NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev        # dev server on :3000
npm run build      # production build
npm run lint       # ESLint
npm run type-check # TypeScript check (tsc --noEmit)
```

### Docker (PostgreSQL + backend)
```powershell
docker-compose up -d   # PostgreSQL (:5432) + backend (:8000); hot-reload via volume mount
```

### Integration Tests (hit live server)
```powershell
cd tests
python test_extraction.py --url http://localhost:8000 --verbose
python test_extraction.py --list-types           # show all 12 doc types
python test_extraction.py --dry-run              # validate test setup without running
# Default URL is production Railway when --url omitted
```

### Poppler (required for pdf2image on Windows)
```powershell
winget install poppler   # or add bin/ from https://github.com/oschwartz10612/poppler-windows to PATH
```

---

## Key Non-Obvious Architecture Decisions

### The extraction pipeline lives entirely in `extract.py`, NOT in `engine/orchestrator.py`

`backend/app/api/routes/extract.py` (~3700 lines) contains the full extraction pipeline inline: template parsing, region analysis, vision prompt building, LLM calls, pdfplumber cross-validation, value normalization, decimal fixup, multi-document detection, etc. It is not a thin route file.

`backend/engine/orchestrator.py` is a separate **CLI/batch-mode** controller that uses Rich for console output. It is NOT called during web API requests.

### Engine connector modules ARE used by the web API

The "engine is not called" rule applies only to `orchestrator.py`. `extract.py` and `drive.py` DO import engine modules:

- `engine/connectors/llm_router.py` → `LLMRouter` — imported by `extract.py`
- `engine/connectors/gemini_client.py` → `GeminiClient` — used via `LLMRouter`
- `engine/connectors/groq_client.py` → `GroqClient` — used via `LLMRouter`
- `engine/connectors/gdrive.py` → imported dynamically by `drive.py`
- `engine/core/preprocessor.py` → PDF preprocessing utilities

**NOT used by the web API** (engine-only): `orchestrator.py`, `excel_writer.py`, `drive_watcher.py` (bridged via `FakeDB`), `core/validator.py`, `core/prompt_builder.py`, `schemas/base_prompts.py`.

### Engine modules on `sys.path`

At the top of `extract.py` and `export.py`, the engine directory is injected onto `sys.path`:
```python
sys.path.insert(0, _backend_dir)   # backend/
sys.path.insert(0, _engine_dir)    # backend/engine/
sys.path.insert(0, _project_dir)   # project root
```
This means `from orchestrator import Orchestrator` and `from connectors.llm_router import LLMRouter` both work. Always start uvicorn from the `backend/` directory.

### `engine/config.py` is a compatibility shim

Engine files do `from config import settings`. `engine/config.py` intercepts that import and re-exports `app.config.settings` (the real Pydantic settings object). If that import fails it falls back to a `SimpleNamespace` built from env vars. The engine has no `.env` of its own — it always uses the app's config.

### Startup migrations run before Alembic

`main.py` lifespan runs `_run_migrations()` which executes idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` SQL on every boot — before Alembic. This adds columns that were added since initial deployment without requiring a migration step per deploy. If a column already exists, the `IF NOT EXISTS` guard is a no-op.

### Template `description` field stores full spreadsheet grid JSON

`ColumnTemplate` has two storage fields:
- `columns_json` — JSON array of `{name, type, order}` column definitions (used for simple template CRUD)
- `description` — full spreadsheet grid layout JSON (used by the template editor to restore the exact cell layout on re-open)

When `extract.py` parses a template, it tries `description` first (grid-based), falls back to `columns_json`.

### Super-admin vs admin vs company_admin vs client

| Role | client_id | Access |
|---|---|---|
| `admin` with no `client_id` | null | Super-admin: sees all users, jobs, templates |
| `admin` with `client_id` | set | Company admin for that org |
| `company_admin` | set | Can share templates within own org |
| `client` | set | Own data only |

Template visibility: own OR `is_default=True` OR (`is_shared=True` AND same `client_id`). Only `admin`/`company_admin` can set `is_shared`.

Note: `UserCreate` schema only validates `role` as `^(admin|client)$`. `company_admin` can exist in the DB but cannot be assigned via the normal create-user API — it must be set directly via `UserUpdate` or SQL.

---

## Backend Architecture

### `backend/app/main.py` — app factory + lifespan

Startup order: `init_db()` → `_run_migrations()` → `ensure_storage_dirs()` → `_seed_admin()` → `_seed_demo_schema()`.

- Default admin: username=`admin`, password=`admin123` (created if no admin exists)
- Demo schema seeded from `backend/engine/demo_accounting.yaml` as `client_id=demo_001` if `client_schemas` table is empty
- Swagger/ReDoc disabled in production (`ENVIRONMENT=production`)

### `backend/app/config.py`

Pydantic `BaseSettings` reading from `.env`. Key settings:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | sqlite dev fallback | Use PostgreSQL in prod |
| `SECRET_KEY` | required | JWT signing (HS256) |
| `GROQ_API_KEY` | required | Primary LLM |
| `GEMINI_API_KEY` | required | Vision + fallback |
| `PRIMARY_LLM` | `groq` | `groq` or `gemini` |
| `GROQ_CLASSIFICATION_MODEL` | `llama-3.2-11b-vision-preview` | |
| `GROQ_EXTRACTION_MODEL` | `llama-3.3-70b-versatile` | |
| `GROQ_VISION_MODEL` | `llama-3.2-90b-vision-preview` | |
| `GEMINI_MODEL` | `gemini-2.0-flash` | engine default |
| `BATCH_SIZE` | 5 | docs per batch |
| `RATE_LIMIT_DELAY` | 2.0s | delay between LLM calls |
| `MAX_RETRIES` | 3 | per LLM call |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `ENVIRONMENT` | `development` | `production` disables Swagger |

Phase-flagged (not yet active): Redis/Celery (Phase 4), S3/R2 (Phase 3).

### `backend/app/models/models.py` — all SQLAlchemy models

5 tables, all SQLAlchemy 2.0 style with `DeclarativeBase`:

- **`users`** — `id`, `username`, `password_hash` (salt:sha256), `role`, `client_id`, `is_active`, `last_login`
- **`extraction_jobs`** — `client_id`, `status` (pending/processing/completed/failed/cancelled), `total_docs/successful/failed/needs_review`, `input_source` (upload/drive/folder), `schema_id`, `total_tokens`, `total_cost`
- **`document_results`** — `extraction_json` TEXT (JSON string, not Column(JSON)), accessed via `get_extracted_data()` / `set_extracted_data()`; `overall_confidence` (high/medium/low); `needs_review`, `reviewed` flags; `latency_ms`, `tokens_used`
- **`column_templates`** — `columns_json` (column list), `description` (full grid JSON), `is_default`, `is_shared`, `client_id`
- **`watch_folders`** — `folder_id` (Drive ID), `processed_file_ids` (JSON list), `poll_interval_minutes`, `is_active`
- **`client_schemas`** — `client_id` (unique), `yaml_content` (raw YAML), `document_types` (JSON list of type names)

SQLite dev config: WAL journal mode, foreign keys ON. PostgreSQL prod config: pool_size=10, max_overflow=20, pool_pre_ping, pool_recycle=3600.

### `backend/app/schemas/schemas.py` — Pydantic API contract

All request/response models live here. Key types:
- `UserCreate` / `UserUpdate` / `UserResponse` — user management
- `JobStatus` / `JobListItem` — extraction job state
- `DocumentResultResponse` / `DocumentUpdateRequest` — per-document results; `DocumentUpdateRequest.extracted_data` is the edited dict sent on cell-level edits
- `TemplateCreate` / `TemplateUpdate` / `TemplateResponse` / `TemplateColumn` — template CRUD; `TemplateColumn.extraction_type` is `"header"` (once per doc) or `"lineitem"` (per table row)
- `ExportRequest` — `job_id`, `template_id`, `selected_columns`, `column_order`, `doc_types`, `include_line_items`, `include_needs_review_only`
- `SchemaResponse` / `SchemaDetailResponse` — YAML schema listing/detail

### `backend/app/core/auth.py`

- `hash_password(pwd)` → `"salt:sha256(salt+pwd)"` (colon-separated, NOT bcrypt)
- `verify_password(plain, stored)` → splits on `:`, recomputes hash
- JWT payload: `{"sub": str(user.id), "role": user.role, "client_id": user.client_id}`
- `get_current_user` FastAPI dependency: decodes JWT, fetches user from DB
- `get_optional_user` variant: returns None without raising for unauthenticated requests
- `require_admin` dependency: checks `current_user.role != "admin"`

### `backend/app/core/storage.py`

Singleton `StorageService` via `get_storage()`. Key path patterns:
- Uploads: `uploads/{job_id}/{filename}`
- Outputs: `outputs/{job_id}/{filename}`
- Schemas: `schemas/clients/{client_id}.yaml`

S3 key format mirrors local paths. `get_local_path(key)` downloads from S3 to `/tmp` if using S3 backend. Set `STORAGE_BACKEND=s3` + AWS/R2 credentials to switch — no route changes needed.

### `backend/app/api/routes/auth.py` — rate limiter

In-memory, thread-safe (`Lock()`), per-IP: `_fail_counts` + `_lockout_until` dicts. 5 failed attempts = 15 min lockout. `_get_client_ip()` respects `X-Forwarded-For` (Railway proxy). Stateless JWT — logout is a no-op on server.

---

## Extraction Pipeline (`extract.py`)

This is the largest and most important file (~3700 lines). The pipeline runs in a background thread spawned by the upload endpoint.

### Key functions in order of execution

1. **`POST /api/extract/upload`** — accepts multipart files + `client_id` + optional `template_id`. Creates `ExtractionJob` record, spawns `_run_extraction_sync()` in `threading.Thread`, returns `{job_id}` immediately.

2. **`_run_extraction_sync()`** — the background thread target. Iterates documents, calls per-document extraction, updates DB. Status transitions: `pending → processing → completed/failed`.

3. **`_detect_documents_in_pdf()`** — multi-document detection. Single-page PDFs: asks LLM vision if multiple docs are on the page (e.g. 2 cheques). Multi-page PDFs: each page = one document. Returns list of `{index, page_indices, hint, sub_index, total_on_page}`.

4. **`_parse_template()`** — reads `ColumnTemplate.description` (full grid JSON) or `columns_json`. Extracts column names + extraction types (header/lineitem).

5. **`_analyse_template_regions()`** — categorizes the template grid into regions:
   - `kv_pairs` — label in col A, value in col B (form-style)
   - `two_col_pairs` — narrow left label column
   - `table_regions` — multi-column tables (line items)
   - `explicit_targets` — cells marked "Extract here" by user
   - `transposed_tables` — horizontal tables (headers in row 1, data in row 2+)
   - `section_label_rows` — decorative headers, not data
   - Returns `primary_mode`: `form_with_targets` | `form_kv` | `table` | `mixed`

6. **`_build_vision_prompt()`** → `(system_instruction, user_prompt)` tuple. `system_instruction` comes from `prompt_registry.py` — the expert persona for the detected document type (12 types).

7. **`_smart_truncate()`** — trims doc text to 3000-8000 chars depending on mode, anchors table sections.

8. **`_build_output_format()`** — generates JSON schema for AI response. Uses SEPARATE array keys per table for multi-table docs (e.g. `"line_items"` and `"tax_lines"` as distinct keys).

9. **`_validate_with_pdfplumber()`** — cross-checks each AI-extracted value against pdfplumber text. Assigns `high` (pdfplumber confirms), `medium` (partial or AI-only), `low` (pdfplumber found nothing).

10. **`_extract_pdf_table_direct()`** — uses pdfplumber line/text strategies as alternative to AI for clear tabular sections.

11. **`_normalize_value(v)`** — normalizes extracted values:
    - Currencies: strips `$£€₹` and commas
    - Accounting negatives: `(2.85)` → `-2.85`
    - Dates → ISO `YYYY-MM-DD`
    - K/M suffix: `5K` → `5000`, `1.2M` → `1200000`
    - Null-like strings → `""`

12. **`_fix_split_decimals()`** — repairs numbers split across page breaks: `"7513.0"` + orphan `"3"` → `7513.03`.

### Sectioned Multi-Pass Extraction (`extract.py` — parallel column templates)

When a parallel-column template has **multiple vertical sections** in the same column band (e.g. a balance sheet where col B is the value column for BOTH Current Assets rows 2-9 AND Current Liabilities rows 14-19), a single LLM call conflates both sections.

**Detection**: `_detect_vertical_sections(group_items)` finds row gaps > 2 between a group's items — a gap indicates a section header row sits between sections.

**Fix**: `_extract_parallel_groups_sectioned()` (called from `_vision_extract_all_documents` before the regular single-pass path when `primary_mode == "parallel_groups"`):
- Makes **one LLM call per vertical section**, each scoped with a "SECTION SCOPE" fence telling the AI to ignore other sections.
- Section header labels for passes 2+ are found by `_find_section_header_in_gap()` which scans the layout cells in the label column between the previous section's last row and this section's first row.
- Results from all passes are merged into one `extracted_fields` dict (cell-ref → value).
- The merged dict is passed to `_process_vision_result()` and written back via the T1 FieldBinding system (`_write_form_excel` / `write_template_row`).
- Falls back to single-pass if only 1 vertical section is detected or all passes fail.

**Rate limiting**: 2-second sleep between sectioned passes (same-document inter-call delay).

### Prompt Registry (`prompt_registry.py`)

1511 lines. `PROMPT_REGISTRY` dict with 12 document types + `"other"` fallback:
`sales_invoice`, `purchase_order`, `cheque`, `receipt`, `pay_order`, `bank_statement`, `payslip`, `expense_report`, `tax_form`, `income_statement`, `balance_sheet`, `audit_report`.

Each entry has: `system` (expert persona prompt), `table_rules`, `auto_classify_hints`, `required_fields`, `numeric_fields`, `date_fields`.

`classify_by_hints()` does keyword pre-screening (no LLM): needs score ≥2, or score=1 with no competing type. `build_classification_prompt()` sends to LLM when hints are ambiguous.

### LLM Routing (`engine/connectors/llm_router.py`)

- `PRIMARY_LLM=groq` (default): Groq first, Gemini fallback
- `PRIMARY_LLM=gemini`: Gemini first, Groq fallback
- For Groq: system_instruction is **prepended** to the user prompt (Groq doesn't split roles for extraction calls)
- For Gemini: system_instruction is sent as **separate body field** (billed at reduced rate by Gemini)

### Gemini Client (`engine/connectors/gemini_client.py`)

Pure `urllib.request` — **no Google SDK dependency**. Auto-discovers working model from `CANDIDATES = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest"]`, caches in `_good_model`. On JSON parse failure: retries with temperature=0. Cost logging at $0.075/1M input + $0.30/1M output.

---

## Export (`export.py`)

Uses **openpyxl directly** — not the engine's `excel_writer.py`.

**Two modes:**
- `POST /api/export/combined` — one sheet all docs as rows + Summary sheet. Header fill = `#4F46E5` (brand indigo). Yellow fill on rows where `needs_review=True`.
- `POST /api/export/perfile` — one sheet per document, Field/Value/Confidence row format.

---

## Templates

`ColumnTemplate.columns_json` stores `[{name, type, order}, ...]`. The `description` field stores the full spreadsheet grid as JSON for editor restore.

### Spreadsheet Editor Component Stack

The template editor is a **custom-built spreadsheet** in `DocAgentSpreadsheet.tsx` — it does NOT use FortuneSheet or Univerjs at runtime despite their presence in the `components/templates/` directory. `FortuneSheetEditor`, `FortuneSheetInner`, and `UniverSheet.tsx` are legacy/alternative implementations that are not currently wired to any page.

- `DocAgentSpreadsheet.tsx` — the active spreadsheet implementation (50×26 canvas grid, custom renderer)
- `TemplateEditor.tsx` — page-level wrapper: loads `DocAgentSpreadsheet` dynamically (SSR-safe), manages template name/doc type, handles save

`SheetSaveData` (exported from `DocAgentSpreadsheet.tsx`) is the data contract between editor and backend:
```typescript
interface SheetSaveData {
  cells: Record<string, Cell>;          // "row,col" → Cell
  colWidths: number[];
  merges: Record<string, { rows, cols }>;
  extractTargets: Array<{ r, c, label, isRepeat }>;
  repeatRows: number[];
}
```
This is serialized to `ColumnTemplate.description` on save and deserialized on load.

`TemplatePreview.tsx` — read-only mini-grid rendered on the Extract page when a template is selected. Reads the same `description` JSON and renders a scaled-down version of the template layout.

---

## Frontend Architecture

### Routing and Pages

Next.js 14 App Router. Pages:
- `/login` — auth form → `authApi.login()` → Zustand store + localStorage
- `/extract` — main UI: template picker + options + file dropzone + AG Grid results + InsightsPanel
- `/history` — job list with status badges, line item expansion, download buttons
- `/templates` — create/edit templates using spreadsheet editor
- `/admin` — user management (create/edit/reactivate/delete), system stats; admin role only
- `/analytics` — cost/usage charts (token counts, cost per job, doc type breakdown); admin role only

### Auth State

`frontend/lib/auth-store.ts` — Zustand store. Token stored in localStorage as `da_token` + `da_token_exp`. `initializeFromStorage()` called on app mount. Auto-redirect to `/login` on 401 from any API call.

`AppLayout` (`components/layout/AppLayout.tsx`) — sidebar nav wrapper for all authenticated pages. Nav items: Extract, History, Templates for all users; Analytics + Admin for `role === "admin"` only.

### API Client (`frontend/lib/api.ts`)

Single typed axios instance. All calls go through here. Key behaviors:
- `Authorization: Bearer {da_token}` header added automatically
- Auto-redirect to `/login` on 401
- `ExtractionOption` type: `"categorize" | "summary" | "anomaly" | "graphs"`
- `"graphs"` option is **filtered out** before sending to backend (frontend-only: generates inline SVG charts from returned data, no chart library)
- API namespaces: `authApi`, `schemasApi`, `templatesApi`, `extractApi`, `exportApi`, `driveApi`, `adminApi`

### Next.js API Proxy

`frontend/app/api/proxy/[...path]/route.ts` — proxies ALL HTTP methods to `BACKEND_URL/api/{path}`. Handles multipart/form-data by passing as blob without setting content-type (lets fetch set boundary automatically). Returns 502 on fetch errors.

### Extract Page (`app/extract/page.tsx`)

Left column: template picker, extraction options, file dropzone. Right column: results.

Job polling via React Query: `refetchInterval: 2000ms` while `pending/processing`, stops on `completed/failed`. `prevStatus` ref prevents duplicate completion callbacks.

`InsightsPanel` renders: categorization pie/bar charts, AI summary text, anomaly list, numeric breakdown graphs — all inline SVG, no chart library dependency.

Extract page sub-components:
- `DriveTab.tsx` — Google Drive file picker tab (alternative to local upload)
- `ExportPanel.tsx` — export controls: format selector, column picker, download button
- `TemplatePreview.tsx` — read-only template grid shown when a template is selected

### ResultsGrid (`components/extract/ResultsGrid.tsx`)

AG Grid (`ag-grid-react`) with editable cells. Cell-level edits call `PATCH /api/jobs/{job_id}/results/{doc_id}`. Custom cell renderers: `ConfidenceCell` (color-coded high/medium/low), `StatusCell` (OK/Review). `TableRowsPanel` shows line items as a nested table.

### React Query + Toast (`frontend/app/providers.tsx`)

`Providers` wraps the app with `QueryClientProvider` (staleTime=30s, retry=1) and `react-hot-toast` `Toaster`. The Toaster uses CSS custom properties from `globals.css` for theming.

### Design System (`app/globals.css`)

CSS custom properties (not Tailwind classes) for all design tokens:
- Surfaces: `--bg #f5f6f8`, `--surface #ffffff`, `--surface2 #f8f9fb`
- Accent: `--accent #4f46e5` (indigo), `--accent-hover #4338ca`
- Semantic: `--green #059669`, `--amber #d97706`, `--red #dc2626`, `--blue #2563eb`
- Sidebar: `--sidebar-w 220px`, `--sidebar-bg #1e2130` (dark), `--sb-active #818cf8`
- Font: Inter (sans) + JetBrains Mono (code)
- Excel export header color matches `--accent`: `PatternFill(fgColor="4F46E5")`

Analytics page hardcodes Gemini 2.5 Flash Lite rate: `$0.00015` per 1K tokens for frontend cost calculations.

---

## Database Schema Notes

### `DocumentResult.extraction_json`

Stored as TEXT (JSON string), not a native JSON column. This ensures compatibility across PostgreSQL and SQLite. Always use `doc.get_extracted_data()` and `doc.set_extracted_data(data)` — never read/write `extraction_json` directly.

### `ColumnTemplate.description`

Dual use: template description text (legacy) AND full spreadsheet grid layout JSON (current). When the value is valid JSON (starts with `{`), it's the grid layout. The `_parse_template()` function in `extract.py` detects which format is present.

### `ClientSchema.yaml_content`

Raw YAML stored in DB AND written to filesystem via `storage.save_schema()`. Both copies are kept in sync on upload.

### `WatchFolder.processed_file_ids`

JSON list of Google Drive file IDs already processed. Prevents re-processing. Updated after each successful extraction from that folder.

---

## Google Drive Integration (`backend/app/api/routes/drive.py`)

Routes: `/api/drive/auth`, `/api/drive/callback`, `/api/drive/folders`, `/api/drive/files`, `/api/watch/*`.

`_get_drive()` dynamically imports `gdrive.py` from engine via `sys.path`. `_do_watch_check()` uses a `FakeDB` adapter class to bridge v2 SQLAlchemy models to the legacy `drive_watcher.py` interface (which expected a different DB object shape).

Watch folder polling: checks every `poll_interval_minutes` (default 5). New files auto-submitted for extraction. `processed_file_ids` JSON list prevents re-processing.

---

## Deployment Workflow

**When asked to deploy any change, always follow these steps in order:**

1. **Make the change** — edit the relevant files
2. **Run tests** — at minimum `npm run type-check` (frontend) and/or a quick smoke-test against the local server if the backend changed
3. **Commit to git** — write a clear, descriptive commit message summarising what changed and why
4. **Push to GitHub** — `git push origin main`
5. **Confirm the push succeeded** — check the output; report the commit SHA and confirm it's on GitHub

Cloud services (Railway for backend, Vercel for frontend) are connected to the GitHub repo and auto-deploy on push to `main`. The user can provide Railway/Vercel dashboard links if direct status checks are needed.

**Local repo path**: `E:\docagent-univer`
**Remote**: GitHub (auto-deploys to Railway + Vercel on push to `main`)
**Production URL**: `https://loving-grace-production.up.railway.app`

---

## Deployment Infrastructure

### Railway (backend + PostgreSQL)

`railway.json` contains only `{"$schema": "..."}` — Railway configuration is managed via the dashboard, not this file.

- Backend: `Dockerfile.backend` at project root — `python:3.11-slim`, installs `gcc + libpq-dev`, runs `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- DB: Railway PostgreSQL service (set `DATABASE_URL` env var)

### Vercel (frontend)

`Dockerfile.frontend` at project root — `node:20-alpine`, accepts `NEXT_PUBLIC_API_URL` build arg, runs `npm run build && npm start`. Or deploy directly via Vercel Git integration.

### Docker Compose (local dev)

`docker-compose.yml` runs PostgreSQL (`postgres:14-alpine`) + backend (hot-reload via volume mount `./backend:/app`). Phase 4 Redis/Celery services commented out.

---

## Phase Roadmap (from SETUP.md)

- **Phase 1 (current)**: FastAPI + Next.js + PostgreSQL + local storage. Background threads for async extraction.
- **Phase 2**: Additional frontend pages (mostly complete now).
- **Phase 3**: S3/R2 storage — set `STORAGE_BACKEND=s3` + credentials, no route changes needed.
- **Phase 4**: Celery + Redis — `_run_extraction_sync()` becomes a Celery task, `threading.Thread(...)` replaced with `run_extraction.delay(job_id, ...)`. Redis services already scaffolded in docker-compose (commented out).
- **Phase 5**: Full production deploy — Railway backend, Vercel frontend, R2 files, Railway PostgreSQL.

---

## Common Gotchas

- **Poppler not installed**: `pdf2image` fails silently; text-based PDFs still work, image-based don't. `winget install poppler` on Windows.
- **"No module named 'orchestrator'"**: uvicorn must be started from `backend/` directory, not project root.
- **Demo schema missing**: `client_schemas` table was non-empty on first boot, blocking seed. Manually POST `demo_accounting.yaml` to `/api/schemas`.
- **Template description field**: If a template was created via the spreadsheet editor, `description` is JSON (not human text). Don't display it as a description string.
- **Graphs option**: Never send `"graphs"` to the backend — it's filtered client-side. Backend will return 422 or ignore it.
- **Rate limiter is in-memory**: It resets on server restart. In multi-instance deploys (Phase 4+), this needs Redis.
- **JWT is stateless**: Logout has no server effect. Short `ACCESS_TOKEN_EXPIRE_MINUTES` is the only invalidation.
- **`columns_json` format**: Can be `["field1", "field2"]` (legacy string array) OR `[{name, type, order}]` (current dict array). `_parse_columns()` in templates.py handles both.
- **Alembic is manual**: Startup migrations (`_run_migrations()`) cover additive column changes. For schema changes (new tables, renames), run `alembic revision --autogenerate` and `alembic upgrade head` manually.
- **`company_admin` role**: Exists in the DB and RBAC logic but `UserCreate` schema only allows `admin|client`. Must be set via `UserUpdate` or direct SQL — it cannot be assigned at user creation through the API.
- **`FortuneSheetEditor` / `UniverSheet` components**: Present in `components/templates/` but not used by any current page. `DocAgentSpreadsheet.tsx` is the active editor.
- **Doc type name mismatch**: Frontend `TemplateEditor` uses `"invoice"` but the prompt registry expects `"sales_invoice"`. Map frontend display values to registry keys carefully when adding new doc types.
