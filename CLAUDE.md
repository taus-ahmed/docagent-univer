# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Companion documents — read these too:**
- `docs/DECISION-LOG.md` — why the engine is the way it is, what was rejected, and what each decision cost. Read before changing extraction behaviour.
- `tests/README.md` — the accuracy harness: gold labels, scorer, runner, cache.
- `docs/TEMPLATE-SHAPE-FUTURE-WORK.md` — the declared-shape migration, deliberately deferred.
- `docs/DEPLOY-RUNBOOK.md` — deployment procedure.

---

## Project Overview

DocAgent v2.0 is a multi-tenant AI-powered document extraction SaaS. PDFs are uploaded, a spreadsheet template's cells are enumerated as addressed slots, Gemini fills each slot and quotes the span it read it from, the spans are verified against pdfplumber text, and the result is written back into the template as Excel. Multi-tenant with `client_id` isolation on every data table, JWT auth, PostgreSQL.

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

### Tests
```powershell
# offline suite (replays cached LLM responses) — all green
backend\.venv\Scripts\python.exe -m pytest

# accuracy run over the 10 labeled gold documents
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode replay
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode replay --no-template
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode record            # live, costs money
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode record --repeat 3 # stability
```

`pytest.ini` deselects `-m live` by default. `-m known_bug` tests **fail on
purpose** — they are the proof the harness can see a bug. The old
`tests/test_extraction.py` (live server, zero asserts) was **deleted**; do not
resurrect it. See `tests/README.md`.

### Poppler (required for pdf2image on Windows)
```powershell
winget install poppler   # or add bin/ from https://github.com/oschwartz10612/poppler-windows to PATH
```

---

## THE EXTRACTION ENGINE — READ THIS FIRST

There is **ONE pipeline**:

```
template grid ──> shape ──> slot-directed extraction ──> slot writer
                   ▲
                   └── no template? infer a grid first, then the same path
```

### What was deleted, and must not come back

Phases 2d and 3 removed ~2,524 lines. If you have read older notes describing
any of the following, those notes were wrong and have been removed from this
file:

| Deleted | Where it was | Why it went |
|---|---|---|
| `USE_NEW_EXTRACTOR` flag | `extract.py` | It was a bare `except Exception` that caught *any* engine error, logged one line, and silently completed the request on a different engine producing a different spreadsheet — with nothing recording which engine ran |
| the legacy inline pipeline | `extract.py` | replaced by slot extraction |
| layout / field / CBM extraction routes | `extractor.py` | replaced by slot extraction |
| the three-layer engine (L1/L2/L3) | `extractor.py` | replaced by slot extraction |
| `compute_binding_map` (8-neighbour cell roles) | `extract.py` | replaced by `template_shape.compute_shape` |
| `_understand_template` + `ColumnTemplate.cell_binding_map` | `extract.py`, `templates.py` | a synchronous Gemini call of up to ~300 s inside a template-save HTTP request |
| `ColumnTemplate.shape_json` | `models.py` | a stored copy can silently disagree with a grid that changed |
| `_VALUE_KW` (16 English keywords) | `template_shape.py` | misrouted any template whose value column was headed `2024`, `USD`, `Q4`, a currency symbol, a non-English word, or nothing |

`main.py::_run_migrations()` actively issues `DROP COLUMN IF EXISTS` for
`cell_binding_map` and `shape_json`. `models.py` carries a comment forbidding
stored derived structure.

The reasoning for each is in `docs/DECISION-LOG.md`.

### The files that matter

| File | Lines | Role |
|---|---|---|
| `backend/engine/extractor.py` | 231 | the single entry point: preprocess → infer if no template → route → `run_slot_extraction` |
| `backend/engine/template_shape.py` | 497 | grid → shape; declared regions; `choose_path` (the arithmetic router) |
| `backend/engine/slot_extractor.py` | 474 | slot enumeration, the prompt, grounding, confidence, the result contract |
| `backend/engine/shape_inference.py` | 253 | no-template: document → inferred template → grid → same path |
| `backend/app/api/routes/extract.py` | 6064 | routes, the background job thread, template parsing, **all Excel writers** |

`extract.py` is **no longer an extraction engine**. It is routes + the job
thread + the writers. `_extract_with_template_inner` is a three-line delegation
to `extractor.run_extraction`.

`backend/engine/orchestrator.py` is a CLI/batch controller; only its
`Orchestrator` (for `.llm`) and `DocumentExtractionResult` are used by the web
API. Also engine-only and unreached by the API: `excel_writer.py`,
`core/validator.py`, `core/prompt_builder.py`, `schemas/base_prompts.py`.

### THE ONE RULE (shape)

```
a cell with text in it  =  a STATIC label
an empty cell           =  a SLOT
```

`extractTarget` is read for migration reporting only and never affects the
shape. There is no second way to mark a cell extractable, so there is nothing
that can disagree.

`compute_shape(grid)` returns:

```python
{"version": 1,
 "header_rows": [9], "label_columns": [0], "value_columns": [1],
 "repeat_bands": [{name, header_row, start_row, end_row, columns, section}],
 "field_slots": [{slot_id, ref, row, col, row_label, col_header, section}],
 "required_columns": 6,        # the widest band — what a path must serve
 "summary": "…"}               # human line, computed HERE, never in TypeScript
```

Detection rules: a repeating band is **≥2 adjacent static cells with empty rows
beneath**; a two-column band is a label/value pair by construction; a band at
the very bottom of the grid with ≥3 columns is treated as a band and expanded
by the writer, while 2 columns stays ambiguous and is **skipped out loud**. A
field slot is a static label with an empty cell beside it — *every* such pair
across the row, so side-by-side layouts do not lose their right half.

**Shape is never stored.** It is a pure function of the grid, costs ~0.2 ms, and
is recomputed on every extraction and every template API response
(`templates.py::template_shape_of`). `POST /api/templates/shape` previews it
for the editor.

### Declared regions — a template declaring its own tables

`grid["regions"]` (set in the editor by selecting a range and marking it a
table) is read by `_declared_bands` **before** detection; detection then covers
everything undeclared, so the 19 production templates that declare nothing are
unaffected.

- `orientation: "rows"` — headings across the region's first row, one record per row.
- `orientation: "columns"` — headings down the first column, one record per column (**transposed**). Detection cannot express this shape at all: it finds no empty rows beneath and reads the headings as unrelated single fields, silently.

⚠ Regions are absolute `(r1,c1,r2,c2)`. The editor can only edit cells in place
today, so a declaration cannot go stale. **Anyone adding row/column insertion
must shift declarations in the same commit** — the exact arithmetic is in the
box comment in `template_shape.py`. A stale declaration is worse than none: it
points confidently at the wrong cells.

### Path selection is arithmetic, not vocabulary

`choose_path(shape, doc_type, slot_doc_types)` asks one question: how many
columns does this template need (`required_columns`), and can the path serve
that many.

```python
PATH_CAPACITY = {"layout": 2, "field": None, "slot": None}
```

`_SLOT_DOC_TYPES = None` in `extractor.py` means **all document types go to the
slot path**. The `layout`/`field` branches in `choose_path` are unreachable
today and kept only as the capacity argument. `choose_path` returning `error`
means no path fits — the document **fails loudly** with a message saying what to
change, never a blank or partial sheet.

### Slot-directed extraction (`slot_extractor.py`)

One Gemini call. Every template cell is an addressed slot; the model fills each
by its address; the answer is written at the address it was requested for.
There is **no matching step afterwards** — which is what removes wrong-cell
placement, silent empty cells, duplicate values, and total-vs-line-item
ambiguity as *representable states*, rather than merely reducing them.

- Field slots are addressed `F1, F2, …` and described by `(section, row_label)`.
- Table rows are answered as one object per document row, keyed by the band's
  column keys. Duplicate headers are disambiguated by column letter, so
  `Current Assets | Amount | Current Liabilities | Amount` does not collapse
  into one key and lose half the sheet.
- A transposed band is answered *identically* — one object per record. Only the
  writer transposes.

**Grounding is mandatory.** Every filled slot returns `{value, source, page}`.
`verify_span` checks the verbatim `source` against document text read with
pdfplumber *independently of the model*, then checks the value sits inside its
own span (string containment, digit containment, or numeric-token equality).
Ungrounded ⇒ the value is kept, marked **low**, and flagged — never presented as
fact. Table rows carry a **row-level** span, which grounds every cell in the row
and additionally catches fabricated and duplicated rows (`seen_sources` dedup).

**The confidence vocabulary is five words, defined once in
`app/core/confidence.py`** — read that docstring before touching any of them:

| level | claim |
|---|---|
| `high` | grounded **and** the USER authored the slot's label. Templated only. |
| `grounded` | grounded, but the MODEL named the slot, so nothing independent says the value *belongs* there. The most no-template extraction can honestly claim. |
| `unverified` | no text layer existed to check any span against (image upload, scanned PDF). Not a middling measurement — no measurement. |
| `low` | checked and failed. |
| `edited` | a human typed it in the results grid. |

`high` and `grounded` are both "confident" (`CONFIDENT_LEVELS`) for the review
gate and the admin stat — **test membership in that tuple, never `== "high"`** —
and are never merged for display. The UI and both Excel exporters spell the
claim out ("Verbatim from the document"); `ResultsGrid.tsx` mirrors the map.

`confidence_for` returns **high** only when grounded **and** `_single_datum`
passes — one piece of information per cell; an email or phone number in a cell
that did not ask for one, or a `|`, demotes to low.

> A stricter span rule (the value must be the whole span, or set off in it by a
> delimiter) was tried and **rejected on evidence**: it demoted 250 correct
> cells to reach 98.4% precision, worse than the 99.5% without it, because a
> correct value read off a line is structurally identical to one truncated at a
> line break. See the NOTE in `slot_extractor.py` and decision-log §2. Do not
> re-add it.

Document-level gates: more than **30%** low-confidence cells ⇒ the whole
document is flagged for review rather than handing the user a wall of per-cell
warnings; scanned/image input or `<50` chars of text ⇒ all confidences floored
to medium with an explanatory note.

### Result contract (`DocumentExtractionResult.extracted_data`)

```python
{"document_type", "overall_confidence", "extraction_method": "slot_directed",
 "extracted_fields": {cell_ref: value},          # what the writer places
 "extracted_data":   {row_label: {value, confidence, ref}},
 "slot_map": {"fields": [...], "tables": [...]}, # geometry for the writer
 "<band name>_rows": [ {col_key: value, "_confidence": "high"} ],
 "validation": {flagged_count, flagged_fields, confidence_map,
                ungrounded_count, low_confidence_ratio,
                document_needs_review, grounded_count},
 "validation_notes": [...], "needs_review": bool,
 "template_type": "slot",                        # authoritative export routing
 "inferred_template", "inferred_grid", "shape_signature",  # no-template only
 "layout_sections": {}, "table_rows": []}        # kept empty for legacy readers
```

**`flagged_fields` is a list of `{ref, value, reason}` dicts — one shape, from
every producer** (`slot_extractor._flag`). It had three: plain strings on the
slot path, `{ref, value, issue}` on the image path, `{ref, value, reason}` on
the legacy one — while both consumers assumed the last. The job runner
summarised each entry with `f['ref']`, which raises `TypeError` on a string, and
that exception was caught by the per-document handler: **any document carrying a
flagged field failed to save**, counted as a failure with the cause only on
stdout. The review panel, reading `.reason` off a string, drew a row of blanks.
`_flag_summary` in `extract.py` still tolerates the old shapes, because a
summary line must never be the reason a document is lost.

### No template: inference, not a second engine (`shape_inference.py`)

`_infer_template_data` makes ONE Gemini call that *designs a template*
(`document_type`, `title`, `fields[]`, `tables[{name, columns[], row_count}]`,
`totals[]`). `build_grid` renders it as the same `SheetSaveData` grid the editor
saves, and from there **nothing downstream can tell the difference** — same
`compute_shape`, same `run_slot_extraction`, same writer.

- `signature(inferred)` = sha256 of the casefolded type / fields / table columns
  / totals. Documents with the same signature share ONE sheet and stack;
  different signatures each get their own sheet (`_write_inferred_sheets`).
- `saveable_template()` produces exactly the payload `POST /api/templates`
  accepts. `GET /api/jobs/{id}/inferred-templates` offers it as "save this as a
  template", one entry per distinct shape. Nothing is auto-saved, and nothing is
  auto-reused on a later job.
- An **empty** template (a grid with no labelled cells) is treated as no
  template at all.
- Inference failing is a hard failure with a message, not a silent fallback.

**Batch schema reuse (Phase 8).** `run_extraction(..., batch_schemas=dict)`
takes a per-JOB cache so documents of the same kind share ONE inferred schema
instead of each inferring a differently-named copy — `_run_extraction_sync`
creates it; every single-document caller passes `None` and infers per document.
Reuse is keyed by `classify_by_hints` (keyword pre-screening, no LLM call) so a
mixed batch still gets one shape per kind, and a reused schema must fill ≥40%
of its slots or the result is **discarded** and that document gets its own
inference. Nothing is persisted beyond the job.

⚠ **Inference is not fully reproducible.** `infer_template` runs at
`temperature=0` (Phase 8), which cut run-to-run field-name variance from 40
fields to 1 — but Gemini gives no reproducibility guarantee even at 0 (no seed
parameter in this REST API). The residual is structural: "what should this
column be called" has several correct answers. See "Measured limits" below.

### Images bypass the slot pipeline

`_is_image_file` (JPG/PNG/WEBP/TIFF/BMP) routes to
`_extract_image_with_template`, which still uses the older
`_build_vision_prompt` → `_process_vision_result` path with
`prompt_registry.py`, marks every value `unverified` (an image has no text
layer, so no span can be checked — it was reported as "medium", which implied a
measurement that never happened), and always sets `needs_review=True`. PDFs — the overwhelming majority — go to
`run_extraction`. This is the one surviving second path.
`_analyse_template_regions`, `prompt_registry.py` and the form/mixed/table
writers exist for it and for re-exporting legacy jobs.

### Export writers (all in `extract.py`)

`_write_excel` routes on the `template_type` persisted in `extraction_json`:

| `template_type` | writer |
|---|---|
| `slot` | `_write_slot_excel` — the current pipeline, always |
| `structural` | `_write_layout_excel` — legacy jobs only |
| `labeled` / `mixed` | `_write_form_excel` / `_write_mixed_excel` / `_write_table_excel` by `primary_mode` — legacy jobs and the image path |
| absent (pre-`template_type` jobs) | falls back to layout-detection on `layout_sections` |

No template ⇒ `_write_inferred_sheets`, one sheet per distinct
`shape_signature`.

`GET /api/jobs/{id}/export` (single workbook) and `/export/zip` (per-file) are
the endpoints. `export.py` additionally serves `POST /api/export/combined` and
`/api/export/perfile`, both openpyxl directly — never the engine's
`excel_writer.py`.

### Measured limits (`tests/reports/latest*.json`, Phase 9)

| | templated | no-template |
|---|---|---|
| **accuracy** (container-aware headline) | **98.5%** | **98.0%** |
| **content** (container-blind) | 97.5% | 96.7% |
| **structure fidelity** | **100%** (17/17) | **100%** (17/17) |
| accuracy RAW (all adapter widenings off) | 47.7% | 70.8% |
| invented (value nowhere in the PDF) | **0** | **0** |
| misfiled | 4 | 6 |
| out-of-schema (*not* a defect) | 0 | 60 |
| **defect rate** | 1.0% | 1.3% |
| fields varying across 3 live repeats | 0 | 1 |

`BS-2024-Q1`, `CHQ-001847`, `IS-2024-Q4` and `STMT-2024-01` score 100% in both
modes. The remaining misfilings are one intermittent bug on one document:
`PAYSLIP-EMP-0012`'s "Total" summary line coming back as a data row.

### The MICR band is parsed, not prompted (`engine/micr.py`)

A cheque's routing and account numbers are printed only inside the MICR band,
so the model returned it whole — asked for a routing number it answered
`A021000021A C7743882201C 001847D`. The band is E-13B, with a sentinel
delimiting each field, so it is parsed: both the real glyphs (`⑆ ⑇ ⑈ ⑉`) and
the ASCII stand-ins different font vendors emit. Slot extraction fills only
slots the model left **empty**, so a real answer is never overwritten, and the
routing number is checked against the **ABA checksum** before use — nine digits
in the transit position that fail it are not reported. `Account Holder` is a
person and is deliberately not matched. `CHQ-001847`: 45.5% → **100%**.

⚠ **Identifiers are not quantities.** `coerce_cell_value` numified any bare
digit run, so extraction held `"021000021"` and the exported cell held
`21000021` — the leading zero gone and the routing number wrong in the
customer's file. A bare digit run with a leading zero, or longer than any
amount written without separators, stays **text**. Money keeps its notation
(symbol, separators, decimal, accounting parentheses); a bare count like a Qty
of 40 is still a number. Caught only by the export-vs-extraction check.

### Naming: the page first, then the canonical vocabulary

`engine/vocabulary.py` turns the registry's `required_fields` /
`numeric_fields` / `date_fields` into the closed label set inference may use,
per document type, chosen by `classify_by_hints` (no LLM call). The order is:

1. **The document's own printed label wins.** An invoice headed `Bill To:` has
   a Bill To field, not a Customer Name field. The page decides, so the name is
   the same on every run *and* it is the name the reader already sees.
2. No printed label (letterhead, signature, stamp, the numbers inside a MICR
   line) → take the name from the list.
3. Printed label ambiguous about *which* value it is → prefer the list's
   precise term (a cheque prints its amount twice).
4. Otherwise `other: <label>`, stripped before it reaches a sheet and counted.
   Currently 1% of labels.

⚠ **The list fixes what things are CALLED, never what gets reported.** The
first version omitted rule 1 and said "use these names in preference to your
own"; the model read that as "do not report what is not listed", dropped the
employer from a payslip and the status from an expense report, and cost one
invoice 34 points. `_EXTRA` fills genuine holes in the registry for the same
reason — a closed list with a hole in it does not mislabel the missing value,
it loses it.

The vocabulary is **standard accounting terminology, not this repo's gold**.
Where they disagree, `GOLD_DIVERGENCE` records it: gold's `Payer Name` is the
**Drawer** (UCC Art. 3), and gold's `Amount` on a cheque is the **Amount in
Figures** (the page states the amount twice and they can disagree).

### Sections and their totals are computed, not asked for

`shape_inference.detect_amount_sections` finds every heading followed by 3+
label/amount lines and hands the model a list it must cover. `_split_total`
then cuts **forward** at the first line that is the section's own total.

Both were prompt rules first and the model applied them inconsistently — five
live samples, three different answers on the same document. They have
arithmetic answers, so they are computed. Detected row counts now equal gold
exactly on both financial statements.

The forward cut is load-bearing: "strip while the last line is a total" stops
one line early (`GROSS PROFIT` follows `Total COGS`), "cut at the LAST total"
keeps `Total Non-Current Assets` as a row (`TOTAL ASSETS` follows it), and only
scanning forward protects a genuine data row that merely reads like an
aggregate — a balance sheet lists `Net Income YTD Q1` *before* `Total Equity`.

Still open: per-client schema persistence.

---

## Backend Architecture

### `backend/app/main.py` — app factory + lifespan

Startup order: `init_db()` → `_run_migrations()` → `ensure_storage_dirs()` → `_seed_admin()` → `_seed_demo_schema()`.

- Default admin: username=`admin`, password=`admin123` (created if no admin exists)
- Demo schema seeded from `backend/engine/demo_accounting.yaml` as `client_id=demo_001` if `client_schemas` table is empty
- Swagger/ReDoc disabled in production (`ENVIRONMENT=production`)
- `_run_migrations()` runs idempotent PostgreSQL DDL on every boot, before Alembic. **It fails loudly**: any failed statement plus `ENVIRONMENT=production` raises and refuses to serve. On non-PostgreSQL dialects it logs a warning that it was SKIPPED rather than reporting success.
- `settings.validate_secret_key()` refuses to boot production on a shipped placeholder `SECRET_KEY`.

### `backend/app/config.py`

Pydantic `BaseSettings` reading from `.env`. Key settings:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | sqlite dev fallback | Use PostgreSQL in prod |
| `SECRET_KEY` | placeholder | JWT signing (HS256); production boot fails on the placeholder |
| `GEMINI_API_KEY` | required | The extraction model |
| `GROQ_API_KEY` | optional | Fallback only |
| `PRIMARY_LLM` | **`gemini`** | `gemini` or `groq` |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Railway production runs `gemini-2.5-flash-lite`; the harness mirrors that |
| `GROQ_CLASSIFICATION_MODEL` | `llama-3.2-11b-vision-preview` | fallback path only |
| `GROQ_EXTRACTION_MODEL` | `llama-3.3-70b-versatile` | fallback path only |
| `GROQ_VISION_MODEL` | `llama-3.2-90b-vision-preview` | fallback path only |
| `BATCH_SIZE` | 5 | docs per batch |
| `RATE_LIMIT_DELAY` | 2.0s | delay between LLM calls |
| `MAX_RETRIES` | 3 | per LLM call |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `ENVIRONMENT` | `development` | `production` disables Swagger and hardens boot |

Phase-flagged (not yet active): Redis/Celery (Phase 4), S3/R2 (Phase 3).

### `backend/app/models/models.py` — all SQLAlchemy models

6 tables, SQLAlchemy 2.0 style with `DeclarativeBase`:

- **`users`** — `id`, `username`, `password_hash` (salt:sha256), `role`, `client_id`, `is_active`, `last_login`
- **`extraction_jobs`** — `client_id`, `status` (pending/processing/**completed/partial/failed**/cancelled), `total_docs/successful/failed/needs_review`, `input_source` (upload/drive/folder), `schema_id`, `total_tokens`, `total_cost`, `progress_message`. A terminal status states what the batch **produced**: `completed` = every document returned a result, `partial` = some did, `failed` = none did. A job where every document failed used to report `completed`, which made a total failure indistinguishable from an empty batch
- **`document_results`** — `extraction_json` TEXT (JSON string, not `Column(JSON)`), accessed via `get_extracted_data()` / `set_extracted_data()`; `raw_llm_response`; `overall_confidence` (high/medium/low); `needs_review`, `reviewed`; `latency_ms`, `tokens_used`
- **`column_templates`** — `columns_json` (column list), `description` (full grid JSON), `is_default`, `is_shared`, `client_id`. **Stores no derived structure** — see the comment in the model
- **`watch_folders`** — `folder_id` (Drive ID), `processed_file_ids` (JSON list), `poll_interval_minutes`, `is_active`
- **`client_schemas`** — `client_id` (unique), `yaml_content` (raw YAML), `document_types` (JSON list)

SQLite dev config: WAL journal mode, foreign keys ON. PostgreSQL prod config: pool_size=10, max_overflow=20, pool_pre_ping, pool_recycle=3600.

### `backend/app/schemas/schemas.py` — Pydantic API contract

- `UserCreate` / `UserUpdate` / `UserResponse` — user management
- `JobStatus` / `JobListItem` — extraction job state
- `DocumentResultResponse` / `DocumentUpdateRequest` — per-document results; `DocumentUpdateRequest.extracted_data` is the edited dict sent on cell-level edits
- `TemplateCreate` / `TemplateUpdate` / `TemplateResponse` / `TemplateColumn` — template CRUD; `TemplateResponse.shape` carries the freshly computed shape
- `ExportRequest` — `job_id`, `template_id`, `selected_columns`, `column_order`, `doc_types`, `include_line_items`, `include_needs_review_only`
- `SchemaResponse` / `SchemaDetailResponse` — YAML schema listing/detail

### `backend/app/core/auth.py`

- `hash_password(pwd)` → `"salt:sha256(salt+pwd)"` (colon-separated, NOT bcrypt)
- `verify_password(plain, stored)` → splits on `:`, recomputes hash
- JWT payload: `{"sub": str(user.id), "role": user.role, "client_id": user.client_id}`
- `get_current_user` dependency decodes the JWT and loads the user; `get_optional_user` returns None instead of raising; `require_admin` checks `role != "admin"`
- **Tenant and template identity come from the token, never the request body** (`resolve_client_id`, `load_template_for_user` in `extract.py`)

### `backend/app/core/storage.py` — one key namespace, two backends

```
clients/{client_id}/jobs/{job_id}/source/{filename}    an uploaded document
clients/{client_id}/jobs/{job_id}/output/{filename}    a generated file
schemas/clients/{client_id}.yaml                       a client's YAML schema
```

Local puts the key under the storage root **verbatim**, so path and key are the
same string. `STORAGE_BACKEND=s3` + credentials switches to any S3-compatible
store (Cloudflare R2 in production) — no route changes.

- **The worker is handed keys, never paths.** A local absolute path is
  meaningless to a separate worker process or a bucket. `_resolve_source` in
  `extract.py` accepts either, so jobs queued before Phase 8 still run.
- **`client_id` leads every tenant-owned key**, so a scoped bucket credential
  or IAM prefix condition can later enforce what the code enforces now.
- **Keys are built in one place** and validated by `_safe_key` (rejects `..`,
  absolute paths, drive letters, backslashes, empty segments); `_local_path`
  re-checks the *resolved* path is inside the root.
- **Reads of a missing file return None, never raise.** A source that retention
  deleted or an ephemeral disk lost is an ordinary state; the worker turns one
  into a failed *document* with an explanatory message, on the same persistence
  path as any other result, so the job still completes. **Writes raise**
  (`StorageError`) — a write that silently failed leaves a job pointing at a
  key holding nothing.
- `signed_url()` (capped at 1 h; **None** on local, so a never-expiring link
  cannot ship by accident) and `delete_job_sources()` (sources go, outputs
  stay) exist for Phase 11 and are tested, but are not yet wired to a route.

⚠ **Schemas must be materialised at boot.** A schema lives twice: the text in
`client_schemas.yaml_content`, and a copy in storage that `get_schema_path()`
hands the engine. `_seed_demo_schema` returns early whenever the table is
non-empty — always, after the first boot — so on an ephemeral container there
was no YAML on disk from the second deploy onward and **every upload answered
404 "No schema found"**. `main.py::_materialise_schemas()` writes them back
from the database at boot, idempotently. Do not remove it.

⚠ **Exports are never stored.** `save_output` is not called by any route:
`GET /api/jobs/{id}/export` rebuilds the workbook from `extraction_json` on
every download. Nothing is lost on restart, and nothing needed migrating.

### `backend/app/api/routes/auth.py` — rate limiter

In-memory, thread-safe (`Lock()`), per-IP: `_fail_counts` + `_lockout_until`.
5 failed attempts = 15 min lockout. `_get_client_ip()` respects
`X-Forwarded-For` (Railway proxy). Stateless JWT — logout is a server no-op.

### Engine modules on `sys.path`

`extract.py` and `export.py` inject the engine directory onto `sys.path`:

```python
sys.path.insert(0, _backend_dir)   # backend/
sys.path.insert(0, _engine_dir)    # backend/engine/
sys.path.insert(0, _project_dir)   # project root
```

So `from extractor import run_extraction`, `from template_shape import
compute_shape` and `from connectors.llm_router import LLMRouter` all work.
**Always start uvicorn from the `backend/` directory.** Functions callable from
a request handler before that has happened (`_compute_shape_for_grid`,
`get_inferred_templates`) re-insert the paths themselves.

### `engine/config.py` is a compatibility shim

Engine files do `from config import settings`. `engine/config.py` intercepts
that import and re-exports `app.config.settings`. If that fails it falls back to
a `SimpleNamespace` built from env vars. The engine has no `.env` of its own.

### LLM routing (`engine/connectors/llm_router.py`)

`LLMRouter.extract()` is the single provider-agnostic chokepoint — every
extraction returns through it, which is where the test harness installs its
record/replay cache.

- `PRIMARY_LLM=gemini` (default): Gemini first, Groq fallback.
- Gemini gets `system_instruction` as a separate body field; Groq gets it
  prepended to the user prompt.
- `image_b64` accepts a **string or a list**; Gemini emits one `inlineData`
  part per page image, Groq gets the first.

`GeminiClient` is pure `urllib.request` — no Google SDK. Auto-discovers a
working model from `CANDIDATES` and caches it in `_good_model`; a
caller-requested `model` is tried first. `responseMimeType=application/json`
forces clean JSON. `temperature=0.1`, no seed — see the reproducibility note
above.

---

## Templates

`ColumnTemplate.description` stores the full spreadsheet grid as JSON;
`columns_json` stores `[{name, type, order}, ...]` for simple CRUD. When
`description` parses as a dict with `"cells"`, it is the grid.

### Spreadsheet editor component stack

The template editor is a **custom-built spreadsheet** in
`DocAgentSpreadsheet.tsx` — it does not use FortuneSheet or Univer at runtime.
`FortuneSheetEditor.tsx`, `FortuneSheetInner.tsx` and `UniverSheet.tsx` are
legacy alternatives wired to no page.

- `DocAgentSpreadsheet.tsx` — the active implementation (50×26 canvas grid, custom renderer)
- `TemplateEditor.tsx` — page wrapper: loads the spreadsheet dynamically (SSR-safe), manages name/doc type, calls `POST /api/templates/shape` to show the engine's own shape summary
- `TemplatePreview.tsx` — read-only mini-grid on the Extract page

`SheetSaveData` is the contract between editor and backend:

```typescript
interface TableRegion { type: "table"; r1: number; c1: number; r2: number; c2: number;
                        orientation: "rows" | "columns"; name?: string }
interface SheetSaveData {
  cells: Record<string, Cell>;          // "row,col" → Cell
  colWidths: number[];
  merges: Record<string, { rows, cols }>;
  repeatRows: number[];                 // DERIVED from regions, not authored
  regions?: TableRegion[];              // declared tables
}
```

Serialized to `ColumnTemplate.description` on save, deserialized on load. The
editor deliberately does **not** re-derive the shape in TypeScript — it asks the
server, so the rule has exactly one implementation.

---

## Frontend Architecture

### Routing and pages

Next.js 14 App Router:
- `/login` — auth form → `authApi.login()` → Zustand store + localStorage
- `/extract` — template picker + options + file dropzone + AG Grid results + InsightsPanel
- `/history` — job list with status badges, line-item expansion, download buttons
- `/templates` — create/edit templates with the spreadsheet editor
- `/admin` — user management + system stats; admin only
- `/analytics` — cost/usage charts; admin only

### Auth state

`frontend/lib/auth-store.ts` — Zustand. Token in localStorage as `da_token` +
`da_token_exp`; `initializeFromStorage()` on mount; auto-redirect to `/login` on
any 401. `AppLayout` is the sidebar wrapper; Analytics + Admin nav items appear
only for `role === "admin"`.

### API client (`frontend/lib/api.ts`)

Single typed axios instance; `Authorization: Bearer {da_token}` added
automatically; auto-redirect on 401. Namespaces: `authApi`, `schemasApi`,
`templatesApi`, `extractApi`, `exportApi`, `driveApi`, `adminApi`.
`ExtractionOption` is `"categorize" | "summary" | "anomaly" | "graphs"`, and
`"graphs"` is **filtered out** before the request — it is frontend-only (inline
SVG from returned data, no chart library).

### Next.js API proxy

`frontend/app/api/proxy/[...path]/route.ts` proxies all methods to
`BACKEND_URL/api/{path}`. Multipart is passed as a blob without setting
content-type so fetch sets the boundary. Returns 502 on fetch errors.

### Extract page (`app/extract/page.tsx`)

Left: template picker, extraction options, dropzone. Right: results. The
template picker is **optional** — extracting with no template is allowed and
routes through the confirmation modal to `startExtract(undefined)`.

Job polling via React Query: `refetchInterval: 2000ms` while
`pending/processing`, stops on `completed/failed`; a `prevStatus` ref prevents
duplicate completion callbacks. Sub-components: `DriveTab.tsx`,
`ExportPanel.tsx`, `TemplatePreview.tsx`. `InsightsPanel` renders categorization
charts, AI summary, anomalies and numeric breakdowns as inline SVG.

### ResultsGrid (`components/extract/ResultsGrid.tsx`)

AG Grid with editable cells; edits `PATCH /api/jobs/{job_id}/results/{doc_id}`.
Renderers: `ConfidenceCell` (high/medium/low), `StatusCell` (OK/Review).
`TableRowsPanel` shows line items nested.

### Providers and design system

`app/providers.tsx` wraps in `QueryClientProvider` (staleTime 30s, retry 1) plus
`react-hot-toast`. `app/globals.css` holds all design tokens as CSS custom
properties — `--bg #f5f6f8`, `--surface #ffffff`, `--accent #4f46e5`,
`--green #059669`, `--amber #d97706`, `--red #dc2626`, `--sidebar-bg #1e2130`;
Inter + JetBrains Mono. The Excel header fill matches `--accent`
(`PatternFill(fgColor="4F46E5")`). The Analytics page hardcodes the Gemini 2.5
Flash Lite rate `$0.00015` per 1K tokens.

---

## Database Schema Notes

- **`DocumentResult.extraction_json`** — TEXT (JSON string), not a native JSON column, for PostgreSQL/SQLite parity. Always use `get_extracted_data()` / `set_extracted_data()`.
- **`ColumnTemplate.description`** — dual use: legacy description text OR the full grid JSON (current). Valid JSON starting `{` with a `cells` key is the grid. `_parse_template()` detects which.
- **`ClientSchema.yaml_content`** — raw YAML in the DB *and* on disk via `storage.save_schema()`; kept in sync on upload.
- **`WatchFolder.processed_file_ids`** — JSON list of Drive file IDs already processed; prevents re-processing.

---

## Google Drive Integration (`backend/app/api/routes/drive.py`)

Routes: `/api/drive/auth`, `/api/drive/callback`, `/api/drive/folders`,
`/api/drive/files`, `/api/watch/*`. `_get_drive()` dynamically imports
`gdrive.py` from the engine via `sys.path`. `_do_watch_check()` uses a `FakeDB`
adapter to bridge the v2 SQLAlchemy models to the legacy `drive_watcher.py`
interface. Watch folders poll every `poll_interval_minutes` (default 5); new
files are auto-submitted.

---

## Deployment Workflow

**When asked to deploy any change, always follow these steps in order:**

1. **Make the change** — edit the relevant files
2. **Run tests** — at minimum `npm run type-check` (frontend) and `python -m pytest` (backend); run the accuracy harness if extraction behaviour changed
3. **Commit to git** — a clear message saying what changed and why
4. **Push to GitHub** — `git push origin main`
5. **Confirm the push succeeded** — report the commit SHA and confirm it is on GitHub

Railway (backend) and Vercel (frontend) auto-deploy from `main`. See
`docs/DEPLOY-RUNBOOK.md`.

**Local repo path**: `E:\docagent-univer`
**Production URL**: `https://loving-grace-production.up.railway.app`

---

## Deployment Infrastructure

### Railway (backend + PostgreSQL)

`railway.json` contains only `{"$schema": "..."}` — configuration lives in the
dashboard. Backend image is `Dockerfile.backend` (`python:3.11-slim`, `gcc +
libpq-dev`, `uvicorn app.main:app --host 0.0.0.0 --port 8000`). DB is a Railway
PostgreSQL service via `DATABASE_URL`.

### Vercel (frontend)

`Dockerfile.frontend` (`node:20-alpine`, `NEXT_PUBLIC_API_URL` build arg), or
the Vercel Git integration directly.

### Docker Compose (local dev)

PostgreSQL (`postgres:14-alpine`) + backend with hot reload via
`./backend:/app`. Phase 4 Redis/Celery services are commented out.

---

## Phase Roadmap

- **Phase 1 (current)**: FastAPI + Next.js + PostgreSQL + local storage; background threads for async extraction.
- **Phase 2**: Additional frontend pages — mostly complete.
- **Phase 3**: S3/R2 storage — set `STORAGE_BACKEND=s3` + credentials, no route changes needed.
- **Phase 4**: Celery + Redis — `_run_extraction_sync()` becomes a Celery task; `threading.Thread(...)` becomes `run_extraction.delay(...)`.
- **Phase 5**: Full production deploy.

(The extraction-engine phases 1–7 referenced throughout this file and in
`docs/DECISION-LOG.md` are a **separate** numbering from this product roadmap.)

---

## Common Gotchas

- **Poppler not installed**: `pdf2image` fails silently; text-based PDFs still work, image-based don't. `winget install poppler` on Windows.
- **"No module named 'extractor'"**: uvicorn must be started from `backend/`, not the project root.
- **Do not store derived template structure.** Shape is recomputed every run on purpose. `cell_binding_map` and `shape_json` are actively dropped at boot.
- **Do not add a bare `except` fallback around extraction.** That was the `USE_NEW_EXTRACTOR` bug: it turned a visible failure into a silently different spreadsheet. A failure must be a failure.
- **Declared regions are absolute coordinates.** Adding row/column insertion without shifting them in the same commit produces confidently wrong extractions.
- **Template `description`**: if authored in the editor it is JSON, not prose. Do not render it as a description string.
- **Graphs option**: never send `"graphs"` to the backend — it is filtered client-side.
- **Rate limiter is in-memory**: resets on restart; multi-instance deploys need Redis.
- **JWT is stateless**: logout has no server effect; short `ACCESS_TOKEN_EXPIRE_MINUTES` is the only invalidation.
- **`columns_json` format**: can be `["field1", ...]` (legacy) or `[{name, type, order}]` (current). `_parse_columns()` handles both.
- **Alembic is manual**: startup migrations cover additive/idempotent DDL only. New tables and renames need `alembic revision --autogenerate` + `upgrade head`.
- **`company_admin` role**: exists in the DB and RBAC logic, but `UserCreate` only allows `admin|client` — it must be set via `UserUpdate` or SQL.
- **`FortuneSheetEditor` / `UniverSheet`**: present but wired to nothing. `DocAgentSpreadsheet.tsx` is the editor.
- **Doc type naming**: the frontend uses `"invoice"` where the prompt registry expects `"sales_invoice"`. Map carefully when adding types.
- **Gold labels are never regenerated from engine output.** If the engine's output shape changes, change `tests/harness/adapter.py` — never `tests/gold/labels/`.
