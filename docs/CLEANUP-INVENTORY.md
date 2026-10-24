# Cleanup inventory (temporary — deleted at the end of the cleanup round)

Taken on `integration/ocr-hardening` after merging 7248a7d. Tools: ruff 0.17
(F401, F841, F811, E722, F821), vulture (80% and 60%, each 60% hit re-checked
with a whole-word `git grep` over backend/ and tests/), a grep orphan-module
finder, a manual import grep for every frontend dependency, a regex secret scan
of tracked files and of every commit reachable from HEAD.

## Top-level layout

| path | purpose | verdict |
|---|---|---|
| `backend/app/` | FastAPI app: routes, auth, config, models, storage | keep |
| `backend/engine/` | extraction engine (on `sys.path`; imports are flat) | keep |
| `backend/engine/core/` | preprocessor (live) + legacy CLI pieces used by `orchestrator.py` | keep; legacy split is a follow-up |
| `backend/engine/connectors/` | Gemini client, LLM router, Drive connector, (Groq client) | Groq removed in task 2 |
| `backend/engine/storage/` | no-op `Database` stub for the legacy CLI | keep (imported by orchestrator, drive_watcher) |
| `backend/engine/schemas/` | legacy prompt text for `prompt_builder` | keep (imported) |
| `backend/alembic/`, `alembic.ini` | migrations | keep |
| `backend/scripts/` | operator scripts | keep `check_demo_docs`, `demo_activity_report`, `migrate_storage_keys` (documented); remove `test_extraction_debug.py` (scratch, writes `debug_output/`, references Groq) |
| `backend/debug_output/` | output of that scratch script, incl. a raw model answer and a stale investigation report | remove |
| `backend/data/test_uploads/` | 2 files used by `tests/test_known_bugs.py`; 3 unreferenced | keep (test data — follow-up) |
| `backend/demo_docs/` | demo account sample documents (served by `demo.py`) | keep |
| `backend/storage/schemas/clients/demo_001.yaml` | tracked although `backend/storage/` is ignored | keep (seed copy; follow-up) |
| `frontend/` | Next.js 14 app | keep |
| `tests/` | pytest suite, harness, gold, fixtures, llm_cache (440 files) | keep |
| `tests/reports/` | committed harness baselines (`latest*.json/.md`, OCR measurements) | **keep tracked**: the runner documents `latest.json` as the committed baseline and the docs cite these files as the evidence for every recorded figure; `history/` is already untracked by the runner |
| `tests/exports/` | four sample workbooks; nothing reads them | remove (generated output) |
| `test_bs_extraction.py` (root) | scratch script for a deleted extraction path; hard-codes a personal path | remove |
| `DEVELOPER_ANALYSIS.md`, `SETUP.md` | old analysis / setup notes | task 4 |
| `docs/` | design docs | task 4 |
| `storage/` (root, untracked) | local runtime dirs | ignored already |

## Static findings

| finding | count | action |
|---|---|---|
| ruff F401 unused imports | 54 | remove (task 3), except re-exports and `noqa` side-effect imports |
| ruff F841 unused variables | 12 | remove where the right-hand side has no side effect |
| ruff F811 redefinitions | 3 | remove the shadowed definition |
| ruff E722 bare except / F821 undefined | 0 | — |
| dead private helpers in `extract.py` (no reference anywhere) | 15 | remove: `_is_text_pdf`, `get_pdf_page_count`, `_get_date_fields`, `_preserve_currency`, `_slug`, `_grid_to_cells_json`, `_field_alias_note`, `_convert_extracted_fields_to_layout`, `_extract_pdf_table_direct`, `_clean_text_for_table`, `_filter_ghost_rows`, `_detect_document_boundaries_vision`, `_make_table_result`, `_col_to_index`, `_get_table_headers` |
| other unreferenced helpers | 6 | remove: `export._ensure_paths`, `prompt_registry.get_required_fields`, `preprocessor.pages_without_text_layer`, `text_layer.gutter_for`, `gdrive.download_folder_files`, `storage.reset_storage` / `cleanup_job` (checked: no route, test, script or doc calls them) |
| vulture hits that are FastAPI handlers, pydantic validators, SQLAlchemy listeners | ~45 | false positives, keep |
| commented-out code blocks | 0 | — |
| TODO / FIXME / HACK / XXX in source | 0 | — |
| `print(` in backend | 93 in extract.py, 11 preprocessor, … | keep: they are the `[TAG]` operational log lines tests and operators read; moving to `logging` is a follow-up |
| duplicate helper names across modules | 12 | `_col_letter` (extract vs template_shape) and `_cell_ref` are identical; the rest share a name only. Consolidation crosses the route/engine boundary — follow-up |
| stray .bak/.orig/.tmp/pyc/caches/node_modules/.next tracked | 0 | — |
| files > 1 MB | 3 | `round2/HTR-043235.pdf` and `round2/HTR-043235 (1).pdf` are **byte-identical** (sha1 3323493…); the copy is part of the 69-PDF corpus several measurements count — follow-up, not deleted |
| `frontend/.env.local` tracked | 1 | untrack + ignore (task 5); not read |
| frontend deps never imported | 10 | `@radix-ui/*` ×6, `clsx`, `js-cookie`, `@types/js-cookie`, `tailwind-merge` — remove |
| frontend: no ESLint config | — | `npm run lint` prompts interactively; follow-up |
| `config.py` comment rules mojibake (`â”€`) | — | fix (encoding only) |

## Secrets (report only — nothing rewritten)

| commit | path | type | status |
|---|---|---|---|
| ecaead9 (2026-04-26, on `main` and `origin/main`) | `.env.example` | Groq API key (`gsk_…`, 56 chars) | replaced in 2584bb6 but **still in published history: rotate/revoke it** |
| — | `.env.example` (HEAD) | `SECRET_KEY` placeholder not in `_PLACEHOLDER_SECRETS` | a production boot from this example would not be refused; fix the example (task 5) |
| — | DB URLs in examples/compose/config | `docagent:docagent@localhost` / `user:pass@host` | placeholders |

No AWS, GitHub, Google, xAI, private-key or JWT token patterns found.
