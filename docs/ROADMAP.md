# Roadmap

What is done, and what remains, in the order it matters to the first customer
(an accountant logging 10 to 50 cheques a day). Design detail for each done
item is in the linked document; each open item says what blocks it.

## Done

| Item | Where |
|---|---|
| One extraction pipeline: template → shape → slot-directed extraction → grounding → writer | CLAUDE.md |
| Scanned pages read through an OCR reader seam (Tesseract), per-page origin, every machine-read value requires review | docs/OCR-READER-SEAM-DESIGN.md |
| Image-covered pages with a thin text layer read by selective OCR (Gate 2c) | §12 `thin_text_layer` |
| Cheques: MICR band parsed, ABA checksum, figures-vs-words cross-check, several cheques per file and per page | `micr.py`, `cheque_*.py` |
| Family validators: cheque, invoice, bank statement, payslip, receipt | `validators.py`, contract §3.3 |
| Possible duplicates across a batch (same cheque scanned twice), flagged on both records | `duplicates.py` |
| Per-family segmenter interface; the cheque logic behind it | `segmenters.py` |
| Review screen: one row per record, badges, filters, page image with the value's box, keyboard review, edit and accept | `ResultsGrid.tsx`, `ReviewPanel.tsx` |
| Marked exports: fill, comment, Review status column, Legend sheet; confirmation before exporting open values | contract §6, DECISION-LOG §23 |
| Named failures for unreadable, password-protected, empty and zero-page files and for provider errors | `extractor._unreadable` |
| Safety invariants under generated input (no OCR value is high, a failed check is low, nothing dropped silently, validators never raise) | `tests/test_safety_properties.py` |
| Passwords hashed with bcrypt; legacy salted SHA-256 hashes upgraded on the next successful login (no migration) | `app/core/auth.py` |
| Parallel OCR (process pool, `OCR_WORKERS`), byte-identical to serial | `core/preprocessor.py`, docs/proposals/throughput.md |
| Every export path marks values needing review | docs/investigations/EXPORT-PATHS.md |
| Reload and deep links keep the session | `frontend/lib/session-gate.ts` |
| One provider seam; Gemini the only provider (Groq removed) | `connectors/llm_router.py` |

## Open

| Item | Why it is open / what blocks it |
|---|---|
| **Handwriting** | A handwritten payee, amount or signature is not read by Tesseract; such a value is `low` with `grounding_failed`, never `high`. Needs a handwriting-capable reader and real samples |
| **Hard scans (a second OCR reader)** | On the synthetic hard tier RapidOCR reads 97 of 155 fields against Tesseract's 35, but 31 of its 97 are wrong; Tesseract is far better on clean and moderate scans. Using both needs an arbitration rule, measured on real client scans. Deferred until real samples exist |
| **Role matrix** | Inventory and recommended matrix in docs/proposals/roles.md. First: watch folders are visible to and deletable by other tenants' admins (`drive.py:274, 331`) |
| **Retention and deletion** | Nothing is ever deleted; design in docs/proposals/retention.md (needs a migration and a default period) |
| **CI** | `.github/workflows/ci.yml` runs once pushed; replay-dependent tests skip by name on another renderer (docs/proposals/replay-portability.md) |
| **Dependency upgrades** | docs/investigations/DEPENDENCIES.md: unused packages and 10 packages with advisories |
| **Access-control cleanup** | Job routes answer 403 for another tenant's job (the review routes answer 404); token revocation on password change |
| **Durable jobs and cancellation** | Extraction runs on a daemon thread: a restart fails the job at next boot, and cancel does not stop work in progress. Needs a queue (Celery + Redis, Phase 4) |
| **Alembic baseline** | Startup DDL covers additive changes only; there is no baseline revision for the current schema |
| **Staging environment** | Changes reach production from `main` directly; a staging service on Railway with its own database |
| **Review history** | Review marks live inside each result (no migration); who changed a mark, and when, is overwritten |
| **Throughput, further** | Parallel OCR is done (2.9× at 50 pages); render once per file and skipping OSD remain (docs/proposals/throughput.md) |
| Roles (`core/permissions.py`, reviewer), 404 across tenants, job cancel and hard delete, `extract.py` split into `app/services/` (round 13) | `docs/SECURITY.md`, `docs/proposals/roles.md` |
| **Cleanup follow-ups** | the legacy CLI modules the API still imports for `Orchestrator.llm`; `print` logging to `logging` |
