# Engine result contract

What `engine/extractor.run_extraction` returns, and what the routes must
**persist unchanged and return unchanged**. This is the spec the route,
the results UI and the exports build on. The engine sets every field below;
a route never derives, renames or drops one. A field listed as optional is
absent, never `null`, unless "or null" is stated.

Reason codes and their meaning: `docs/OCR-READER-SEAM-DESIGN.md` §12 (the one
reference; this file does not repeat their definitions).

---

## 1. Per file — the return value

`run_extraction(...) -> list[DocumentExtractionResult]`: **one entry per
document record**, in reading order. One file gives N records when it holds N
documents (several cheques, one per page or several per page). Never an empty
list.

| field | type | set by | meaning |
|---|---|---|---|
| `filename` | str | extractor | the file's name; with N > 1 records, `"<name> [k of N]"` |
| `success` | bool | engine | `False` = a named failure (`error` says why); nothing extracted |
| `error` | str | engine | `""` on success |
| `document_type` | str | engine | e.g. `"cheque"` |
| `processing_time_ms` | int | engine | |
| `extracted_data` | dict | engine | the record, §2. Persist as JSON **verbatim** (`DocumentResult.extraction_json`) |

A failed record (`success: False`) has no `extracted_data` contract beyond
being absent or empty; the route stores and shows `error`.

### 1.1 How the routes return it

| engine field | route field | rule |
|---|---|---|
| `filename` | `filename` | only the engine's `" [k of N]"` suffix is kept: the route puts it on the UPLOADED name (`_result_display_name`), so the stored name is `"<original_filename> [k of N]"`, or the bare `original_filename` for a single-record file. The engine's own base name (a storage key or temp file) never reaches the user |
| — | `original_filename` | the bare upload name, the same on every record of one file |
| `extracted_data` | `extracted_data` | verbatim, EXCEPT the optional post-processing below |
| `error` | `validation_errors` | `error`, else the result's `validation.errors` joined with `"; "`; a balance sheet / income statement whose section totals disagree (route gate H2) has that warning appended. A failure also shows in the job's failed count and as `document_type: "unknown"` |
| `validation.flagged_fields` | `validation_warnings` | a one-line summary of the flags (`_flag_summary`), when a route gate says the record needs review; the full list stays in `extracted_data` |
| `processing_time_ms` | `latency_ms` | |
| `success` | — | not returned per file; see `validation_errors` |
| `extracted_data["needs_review"]` | stored `needs_review` | the engine's value OR any route gate; a route can raise it, never clear it |

Results are returned sorted by `(original_filename, document_index, id)`, the
name compared case-folded (and `filename` used where an older row has no
`original_filename`); a record without `document_index` (a single-record file)
sorts as index 1.

**Optional post-processing (`options`).** Only when the upload asks for it and
the record succeeded, the job thread adds keys to `extracted_data` before
storing it — each is one extra model call, and none touches a value, a level or
a reason:

| option | key added | when |
|---|---|---|
| `categorize` | `Category` on each row of `table_rows` (`_post_categorize`) | only when `table_rows` is non-empty and its first row has no `Category`; a band named anything else (`<name>_rows`) is not categorized |
| `summary` | `summary` (str) (`_post_summarize`) | when `extracted_data` has no `summary` yet |
| `anomaly` | `anomalies` ([str], at most 5) (`_post_anomaly`) | when `extracted_data` has no `anomalies` yet |

`graphs` is filtered out by the frontend and never reaches the route. A
post-processing call that fails is logged and leaves the record as it was.

**Route review gates** that can raise the stored `needs_review`: any flagged
field; H1 — a `low` value on a `balance_sheet`, `income_statement`, `payslip`
or `sales_invoice`; misaligned rows (`validation.alignment_misaligned`); H2
above; any `review_required` / `_review_required` anywhere in the stored
payload (`_value_requires_review`); the result's own `validation.needs_review`.

### 1.2 Who may read a result

Every job and result route (`/api/jobs/{id}…`, `/api/export/combined`,
`/api/export/perfile`) answers **404 `{"detail": "Job not found"}`** for a job
the caller may not see — another firm's job, or another user's job for a plain
user — exactly as for an id that does not exist, so an id in another tenant
cannot be told apart from a missing one. A super-admin (role `admin`, no
`client_id`) sees every tenant's job.

After a hard delete (`DELETE /api/jobs/{id}/data`) the job answers with
`deleted_at` set and `/results` returns `[]`: the result records described
below no longer exist. The job's counts are kept so history adds up.

## 2. Per document record — `extracted_data`

| field | type | allowed / meaning |
|---|---|---|
| `extraction_method` | str | `"slot_directed"` |
| `template_type` | str | `"slot"` — export routing |
| `document_type` | str | as above |
| `overall_confidence` | str | `high` \| `grounded` \| `medium` \| `unverified` \| `low` |
| `needs_review` | bool | **True whenever ANY value has `review_required` True** (the invariant), or a document-level fact below requires it |
| `extracted_fields` | {cell_ref: str} | what the writer places, e.g. `{"B6": "$3,572.78"}` |
| `field_provenance` | {cell_ref: Provenance} | §3.1, one per key of `extracted_fields` |
| `extracted_data` | {label: {value, confidence, ref}} | label-keyed projection; the results grid edits this |
| `<table>_rows` | [Row] | §3.2, one list per template table (a table named `table` writes `table_rows`) |
| `slot_map` | {fields: [{slot_id, ref, row_label, section}], tables: [...]} | template geometry for the writer |
| `validation` | Validation | §2.1 |
| `validation_notes` | [str] | human sentences, in order; display only, never parse |
| `document_index` | int | k of N — **only when the file gave N > 1 records** |
| `document_count` | int | N — same condition |
| `source_pages` | [first, last] | FILE page numbers (1-based) — same condition |
| `inferred_template`, `inferred_grid`, `shape_signature`, `inferred_label_provenance` | dict or null | no-template runs only |
| `raw_llm_responses` | [str] | audit; not for display |

### 2.1 `validation`

| field | type | meaning |
|---|---|---|
| `confidence_map` | {cell_ref: level} | the level of every field value |
| `flagged_fields` | [{ref, value, reason}] | one shape only; `ref` is the slot's LABEL, `reason` a sentence |
| `flagged_count` | int | always `len(flagged_fields)` (set last, by the extractor) |
| `page_origins` | {file page: `native` \| `ocr` \| `pre_ocr`} | pages this record was read from (keys are strings after JSON) |
| `page_gates` | {file page: {origin, graded_cells, low_confidence_cells, low_confidence_ratio, review_gate, text_floor, selective_ocr?, thin_text_layer?}} | per-page gate; `selective_ocr` / `thin_text_layer` as on `ocr_pages` / `thin_text_layer_pages` below, only on such a page |
| `ocr_pages` | [{page, words, rotated, deskewed, skew_detector, retry, dpi, reader, reader_version, selective_ocr?}] | every OCR'd page of this record. `skew_detector`: `dark` \| `none`; `retry`: `none` \| `crop_psm6`. `selective_ocr` = {image_cover, native_words, ocr_words, ratio, cover_threshold, ratio_threshold}: a page WITH a text layer read by OCR because one image covers it (≥ 0.99) and its layer holds under half OCR's words (Gate 2c) |
| `ocr_failed_pages`, `ocr_zero_word_pages` | [int] | named failures; non-empty ⇒ `needs_review` |
| `thin_text_layer_pages` | [int] | Gate 2c pages that qualified for selective OCR where OCR failed or read nothing, so they stayed native; non-empty ⇒ `needs_review`, `thin_text_layer` on their values, a flag per page. Not listed in `ocr_failed_pages` (those pages HAVE a text layer) |
| `routing_checksum` | `pass` \| `fail` \| null | the MICR band's transit field; null = no band read. Set by the `aba_checksum` validator, which runs for EVERY family |
| `micr_band_unreadable` | true | optional, cheque family — a band is printed, no digit of it readable |
| `possible_multiple_documents` | {micr_bands: int, readable: int} | optional — the record may hold several cheques; kept as one |
| `possible_duplicate` | {of: [filename]} | optional, set by the job runner across a batch — the same cheque (routing + account + serial, and amount and date where both have them) appears in the named records too; `possible_duplicate` on the identity values, `needs_review` |
| `source_region` | {page, index, of, box_pt: [x0, top, x1, bottom], frame} | optional — this record is cheque `index` of `of` on `page`; box in points, top-left origin, in the frame of the STRAIGHTENED page image |
| `selected_pages_ignored` | [any] | optional — requested pages this file does not have |
| `shredded_pages`, `unchecked_overprint_pages`, `unchecked_shred_pages` | [int] | optional — text-layer checks found / not performed |
| counters | int | `ungrounded_count`, `misplaced_count`, `dropped_row_count`, `empty_row_count`, `off_schema_key_count`, `unbound_row_count`, `merged_column_count`, `overprinted_count`, `unwitnessed_count`, `low_confidence_cells`, `graded_cells`, `grounded_count` |
| `low_confidence_ratio` | float | |
| `document_needs_review` | bool | the >30%-low gate alone (NOT the same as `needs_review`) |
| `regions` | [{table, pages, kept_page, kept_rows, left_out}] | a table matched on several pages |

## 3. Per value

### 3.1 A field — `field_provenance[cell_ref]`

| field | type | allowed / meaning |
|---|---|---|
| `source` | str | the quote the value was read from |
| `page` | int or null | FILE page; null = the quote is on several pages and nothing chose one |
| `grounded` | bool or null | the span check; null = set aside before it (its reason says why) |
| `origin` | `native` \| `ocr` \| `pre_ocr` | the page's origin |
| `review_required` | bool | exactly True or False, never absent |
| `review_reasons` | [code] | §12 codes: origin first, then each failed check. `[]` ⇔ nothing owed |
| `amount_cross_check` | `match` \| `mismatch` \| `unreadable` | optional — only on Amount in Figures / Amount in Words. Evidence, never raises a level |
| `aba_checksum` | `pass` \| `fail` | optional — only on a filled routing slot (any family) |
| `lines_check` | `pass` \| `fail` \| `unreadable` | optional, invoice and receipt families — only on the Subtotal: do the line items sum to it |
| `totals_check` | `pass` \| `fail` \| `unreadable` | optional, invoice and receipt families — on every value of subtotal + charges (a receipt's tip / fees) + tax - discount = total |
| `balance_check` | `pass` \| `fail` \| `unreadable` | optional, bank-statement family — on opening, total credits, total debits and closing balance: opening + credits - debits = closing |
| `running_balance_check` | `pass` \| `fail` \| `unreadable` | optional, bank-statement family — on the opening / closing balance, when the transaction rows' balance chain was checked against it |
| `net_pay_check` | `pass` \| `fail` \| `unreadable` | optional, payslip family — on gross pay, total deductions and net pay: gross - deductions = net |
| `deductions_check` | `pass` \| `fail` \| `unreadable` | optional, payslip family — only on Total Deductions: do the listed deductions sum to it |

The level is `validation.confidence_map[cell_ref]` (`high` \| `grounded` \|
`unverified` \| `low`; `edited` after a person types it). Display rule: a value
whose `review_required` is True is shown as needing review whatever its level.

### 3.2 A table row — `<table>_rows[i]`

Column keys hold values; underscore keys are metadata:
`_confidence` (level), `_source` (str), `_page` (int or null),
`_ungrounded` ([column key], optional), `_origin`, `_review_required` (bool),
`_review_reasons` ([code]). A family validator that addresses a row (invoice
totals: `totals_*`; bank running balance: `balance_*`; payslip deductions:
`payslip_*`) sets `_confidence` and
`_review_reasons` there exactly as it does on a field.

## 3.3 Who sets the checks: the validator registry

Cross-field checks are registered per document FAMILY in
`engine/validators.py`; the family comes from the template's `doc_type`
(`cheque`/`check`; `invoice`/`sales_invoice`/...; `bank_statement`/
`bank_statements`/`account_statement`; `payslip`/`pay_slip`/`payslips`/
`pay_stub`/`paystub`/`pay_stubs`/`salary_slip`; `receipt`/`receipts`/
`till_receipt`/`expense_receipt`/`sales_receipt`/`cash_receipt`). Every result is applied by
one rule: `fail` → each affected value exactly `low`, `review_required`, the
check's reason; `unreadable` → the reason added, no level change; `pass` →
evidence only (the provenance keys above), never a raised level. A family with
nothing registered gets none of these keys.

| family | validator | evidence key | reason codes |
|---|---|---|---|
| every family | `aba_checksum` | `aba_checksum`, `validation.routing_checksum` | `checksum_failed` |
| cheque | `amount_cross_check` | `amount_cross_check` | `amount_mismatch`, `amount_unreadable` |
| cheque | `micr_band_unreadable` | `validation.micr_band_unreadable` | `micr_band_unreadable` |
| invoice | `invoice_totals` | `lines_check`, `totals_check` | `totals_mismatch`, `totals_unreadable` |
| bank_statement | `bank_balances` | `balance_check`, `running_balance_check` | `balance_mismatch`, `balance_unreadable` |
| payslip | `payslip_totals` | `net_pay_check`, `deductions_check` | `payslip_mismatch`, `payslip_unreadable` |
| receipt | `receipt_totals` | `lines_check`, `totals_check` | `receipt_mismatch`, `receipt_unreadable` |

A sum or chain over table rows does not run on a table a gate dropped rows
from (`CheckContext.incomplete`): the drop is already flagged, and a check over
what is left would call correct values wrong. The invoice and receipt lines
checks, the bank running balance and the payslip deductions sum all consult it.

## 4. Examples (abridged: only the keys discussed)

**(a) A native cheque, everything verified.** One record; no
`document_index`.

```json
{"needs_review": false, "overall_confidence": "high",
 "extracted_fields": {"B6": "$3,572.78", "B7": "three thousand five hundred seventy-two and 78/100", "B10": "021000021"},
 "field_provenance": {
   "B6": {"source": "$3,572.78", "page": 1, "grounded": true, "origin": "native",
          "review_required": false, "review_reasons": [], "amount_cross_check": "match"},
   "B7": {"source": "three thousand ... 78/100", "page": 1, "grounded": true, "origin": "native",
          "review_required": false, "review_reasons": [], "amount_cross_check": "match"},
   "B10": {"source": "A021000021A C7743882201C 001847D", "page": 1, "grounded": true,
           "origin": "native", "review_required": false, "review_reasons": [], "aba_checksum": "pass"}},
 "validation": {"confidence_map": {"B6": "high", "B7": "high", "B10": "high"},
                "page_origins": {"1": "native"}, "routing_checksum": "pass", "flagged_fields": []}}
```

**(b) A scanned cheque whose figures disagree with its words.**

```json
{"needs_review": true, "overall_confidence": "unverified",
 "field_provenance": {
   "B6": {"source": "$8,572.78", "page": 1, "grounded": true, "origin": "ocr",
          "review_required": true, "review_reasons": ["ocr_origin", "amount_mismatch"],
          "amount_cross_check": "mismatch"},
   "B7": {"source": "three thousand five hundred seventy-two and 78/100", "page": 1,
          "grounded": true, "origin": "ocr", "review_required": true,
          "review_reasons": ["ocr_origin", "amount_mismatch"], "amount_cross_check": "mismatch"},
   "B5": {"source": "Pay to the order of Maria Gonzalez", "page": 1, "grounded": true,
          "origin": "ocr", "review_required": true, "review_reasons": ["ocr_origin"]}},
 "validation": {"confidence_map": {"B6": "low", "B7": "low", "B5": "unverified"},
                "page_origins": {"1": "ocr"},
                "ocr_pages": [{"page": 1, "words": 31, "rotated": 0, "deskewed": 0.0,
                               "skew_detector": "dark", "retry": "none", "dpi": 300,
                               "reader": "tesseract", "reader_version": "5.x"}],
                "flagged_fields": [{"ref": "Amount in Figures", "value": "$8,572.78",
                   "reason": "amount in figures (8572.78) and amount in words (3572.78) disagree — at least one of them is wrong"}]}}
```

**(c) One scanned page holding three cheques** → `run_extraction` returns
THREE records, each like (b) for its own cheque, plus:

```json
[{"filename": "batch.pdf [1 of 3]", "extracted_data": {"document_index": 1, "document_count": 3,
   "source_pages": [1, 1], "validation": {"source_region": {"page": 1, "index": 1, "of": 3,
   "box_pt": [97.0, 57.0, 472.0, 230.0], "frame": "straightened page image, points from its top-left"}}}},
 {"filename": "batch.pdf [2 of 3]", "extracted_data": {"document_index": 2, "...": "index 2 of 3, its own box"}},
 {"filename": "batch.pdf [3 of 3]", "extracted_data": {"document_index": 3, "...": "index 3 of 3, its own box"}}]
```

If the page cannot be cut with confidence it is ONE record instead, with
`validation.possible_multiple_documents: {"micr_bands": 3, "readable": 3}` and
`"possible_multiple_documents"` in every value's `review_reasons`.

## 5. What the route must do

- Store each record as its own `DocumentResult` row: several rows can share one
  file and one page; return them sorted by `(original_filename,
  document_index, id)` (§1.1).
- Return `extracted_data` verbatim. The stored `needs_review` for the row and
  the job counts is `extracted_data["needs_review"]` OR the route's own gates.
- Send images (JPG/PNG) to `run_extraction` like PDFs, so they get this
  contract (`_run_extraction_sync`, `_is_image_file`). ⚠ Only when EVERY record
  the engine returns for an image failed does the route fall back to the
  vision-only path (`_extract_image_with_template`); that record does not
  follow this contract (no `field_provenance`, no per-value review metadata,
  every value `unverified`, `needs_review` True).
- Exports mark every value a person still owes a look (fill, comment, a
  `Review status` column) and every export carries a `Legend` sheet; the rule
  is `app/core/review.py`, shared with the review screen (§6).
- Record the source document's storage key on the row (`DocumentResult.s3_key`)
  so the review screen can show the page the value was read from.

## 6. Review state — written by people, after extraction

Review marks are stored INSIDE the record's `extraction_json`, so they need
no schema change; the engine never writes them.

| key | written by | meaning |
|---|---|---|
| `field_provenance[ref].reviewed` | `POST /api/jobs/{j}/docs/{d}/review` | `{by, at}` — a person looked at this value and accepted it |
| `<table>_rows[i]._reviewed` | same | `{by, at}` for every value of that row |
| `review` | same, `scope: "document"` | `{document_reviewed: true, by, at}` — the whole record accepted |
| `field_provenance[ref].edited`, `.original_value`; `validation.confidence_map[ref] = "edited"` | `PATCH .../fields/{ref}` | a person typed the value; the machine's value is kept |
| `<table>_rows[i]._edited`, `._original` | `PUT .../docs/{d}` | the same, per column of a row |

A value's review status (`verified`, `grounded`, `unverified`, `low`,
`edited`, `empty_flagged`, `empty`, `unknown`) and whether it is still
unresolved are computed from these keys and the engine's own — never stored —
by `app/core/review.py`, and served by `GET /api/jobs/{j}/review`.

## 7. Known limitations

- **A native cheque with no MICR line gets no MICR reason.** Every MICR check
  needs a band to look at; a digital cheque whose band is absent from the text
  layer (an image, or not printed) carries neither `micr_band_unreadable` nor
  `checksum_failed`, and its native values may be `high` with
  `review_required: false`. Its routing and account then come only from the
  model's reading of printed labels, checked by grounding alone.
- The cheque limitations in `docs/OCR-READER-SEAM-DESIGN.md` §12.1 apply.
