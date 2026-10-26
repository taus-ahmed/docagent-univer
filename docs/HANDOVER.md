# Handover — for the partner or a hired maintainer

## What the product is

DocAgent reads accounting documents (invoices, bank statements, cheques,
payslips, financial statements, forms) and fills a spreadsheet. A firm draws a
template (its labels; the empty cells are what to fill), uploads PDFs or
images, and gets an Excel file where every value carries the words it was read
from and its page. A value is "verified" only when those words are found in
the document's own text layer; anything else is marked for review, in the app
and in the export. Several client firms share one deployment and never see
each other's data. Running it: [OPERATIONS.md](OPERATIONS.md); a new firm:
[ONBOARDING-A-CLIENT.md](ONBOARDING-A-CLIENT.md).

## Repository map

| Path | What |
|---|---|
| `backend/app/main.py` | app factory, boot order (migrations, schemas, stranded jobs, retention task), no-store middleware |
| `backend/app/api/routes/` | HTTP routes: `extract.py` (upload, jobs, exports, delete, usage), `review.py`, `templates.py`, `schemas.py`, `admin.py` (users, firms), `auth.py`, `drive.py`, `export.py`, `demo.py` |
| `backend/app/services/` | moved out of `extract.py` in round 13: `job_worker.py` (the job thread), `excel_slot.py` / `excel_legacy.py` / `excel_cells.py` (every Excel writer), `template_parsing.py`, `vision_prompts.py`, `result_processing.py`, `uploads.py` (file checks), `edits.py`, `prompt_registry.py` |
| `backend/app/core/` | `auth.py` (tokens, passwords, one-time passwords), `permissions.py` (`can()`: the role matrix), `storage.py` (keys, local/R2), `job_lifecycle.py` (hard delete), `retention.py`, `usage.py` (page limit), `tenants.py` (create a firm), `review.py`, `confidence.py`, `export_marks.py`, `demo*.py` |
| `backend/engine/` | extraction: `extractor.py` (entry), `template_shape.py`, `slot_extractor.py`, `shape_inference.py`, `text_layer.py`, `doc_boundaries.py`, `core/preprocessor.py`, `ocr_source.py`, `validators.py` + `*_validators.py`, `segmenters.py` / `cheque_segmenter.py`, `micr.py`, `connectors/` (Gemini) |
| `frontend/` | Next.js app (`app/` pages, `components/`, `lib/api.ts`) |
| `tests/` | the suite; `tests/http/` goes through the real app; `tests/harness/` the accuracy harness; `tests/gold/` labelled documents |
| `scripts/` | `prepush_check.py`, `create_tenant.py`, `check_firm_ids.py` (read-only, before a deploy), `trial_report.py`, split tools |
| `docs/` | this folder; the reasoning behind the engine is `DECISION-LOG.md` |

## The three checks

```
backend\.venv\Scripts\python.exe -m pytest                         # suite, offline
backend\.venv\Scripts\python.exe scripts\prepush_check.py          # everything before a push
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode replay [--no-template]
```

The suite and the harness run **offline**: every model call is replayed from
`tests/llm_cache/` (keyed by the exact request; a request never recorded fails
loudly as a cache miss rather than calling Google). `--mode record` calls the
live API and costs money. Accuracy must stay at **97.2% templated / 96.7% no
template** and the native readings of the 69 test PDFs must match
`tests/reports/native_hashes.json`. **Poppler** must be on PATH (page
rendering; `winget install poppler`), and Tesseract for the OCR tests.
Details: [../tests/README.md](../tests/README.md),
[RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md).

## Adding a document family

1. **Template:** draw it in the editor (labels typed, value cells empty);
   nothing in code is needed for a new layout.
2. **Vocabulary / registry:** add the type to
   `backend/app/services/prompt_registry.py` (`required_fields`,
   `numeric_fields`, `date_fields`) and its keywords for `classify_by_hints`
   (the no-LLM page classifier).
3. **Validators:** a `<family>_validators.py` registering checks in
   `engine/validators.py` (see `invoice_validators.py`); a failed check marks
   the value low and gives a reason code.
4. **Segmenter** (only if one file holds several documents of that family):
   `engine/segmenters.py`.
5. **Gold:** a labelled document under `tests/gold/` and a recorded answer;
   never regenerate labels from engine output.

## Reading the reason codes

Every value needing review carries reason codes (`GET /api/review/reasons`
lists them with labels; defined in `app/core/review.py`, explained in
[OCR-READER-SEAM-DESIGN.md](OCR-READER-SEAM-DESIGN.md) §12): e.g.
`grounding_failed` (quote not found), `ocr_origin` (read from a scan),
`amount_mismatch`, `possible_duplicate`.

## Known limitations

See [KNOWN-LIMITATIONS.md](KNOWN-LIMITATIONS.md). In short: handwriting is not
read reliably; hard scans and photographs are read by OCR and never marked
verified; prompts, labels and checks are English (a non-English document
works but the prose checks are silent); European number formats are a known
gap; families beyond invoices, statements, cheques, payslips, receipts,
financial statements and a few forms have no validators.

## Open proposals

`proposals/roles.md` (explicit platform-admin role, a data migration),
`proposals/retention-v2.md` (per-firm periods, firm deletion, audit table),
`proposals/throughput.md` (Celery/Redis, more than one instance),
`proposals/replay-portability.md`.

## Still open — manual items

1. **Leaked key:** commit `ecaead9` on `main` holds an old provider API key —
   revoke it at that provider (history is not rewritten).
2. **Railway variables:** delete `GROQ_*`; check `PRIMARY_LLM`.
3. **`DEMO_CLIENT_IDS`** names only the demo tenant.
4. **License:** none chosen; add `LICENSE`.
5. **Third-party sample PDFs** in `tests/test_pdfs/round2/`: check
   redistribution terms.
6. **Staging** environment before real client documents.
7. Every **VERIFY** in [OPERATIONS.md](OPERATIONS.md) and
   [CLIENT-DATA-FAQ.md](CLIENT-DATA-FAQ.md).
8. Set `DRIVE_TENANT` if anyone used Google Drive (it is off by default);
   confirm Railway appends the client address last in `X-Forwarded-For`
   (else set `TRUSTED_PROXY_COUNT`).
9. Before the first deploy of this release, run `scripts/check_firm_ids.py`
   on the production firm ids ([OPERATIONS.md](OPERATIONS.md) §12).
