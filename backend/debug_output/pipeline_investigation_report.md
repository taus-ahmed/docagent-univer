# DocAgent — Extraction Pipeline Investigation Report
_Read-only investigation. No code changed. Generated from real code + real local DB + live function runs._

> **Scope note (read first).** The local Postgres DB contains **no grid-based templates and no "BS Luq" balance-sheet template** — only 3 legacy `columns_json` "invoice" templates, and the only `document_results` rows are old field-name-keyed invoice runs. The test PDF on disk is an **income statement**, not a balance sheet. Therefore:
> - Parts that can use **real local data**: A1 (schema + rows), A2 (endpoint code), B3 (real raw Gemini JSON from the last run), D1/D2/D3 (save + real rows + export).
> - Parts about the **balance-sheet template specifically** (A3, B1, B2, E2) are answered by **running the actual production functions** (`_parse_template`, `_analyse_template_regions`, `_build_vision_prompt`, `_build_output_format`) on a **representative balance-sheet grid I constructed in memory**. That output is real code output, not fabricated — but the input grid is a stand-in for the production "BS Luq" template, which lives only in the Railway production DB.

---

## 1. Template storage (Part A)

### A1 — `ColumnTemplate` schema (`backend/app/models/models.py:147`)

| Column | Type | Stores |
|---|---|---|
| `id` | Integer PK | |
| `user_id` | Integer FK→users | owner |
| `client_id` | String(100) | owning company (⚠️ **missing from the local DB table** — schema drift; ORM reads fail, raw SQL works) |
| `name` | String(200) | template name |
| `document_type` | String(100) | e.g. `invoice`, `balance_sheet` |
| **`description`** | **Text** | **the full spreadsheet grid the user designed, as a JSON string** (the `SheetSaveData` blob: `{cells, colWidths, merges, extractTargets, repeatRows}`) |
| `columns_json` | Text | legacy flat column list `[{name,type,order}]` |
| `column_order_json` | Text | explicit ordering (usually null) |
| `is_default`, `is_shared` | Boolean | visibility |
| `created_at`, `updated_at` | DateTime | |

- **Which column holds the grid?** `description`. It is **JSON stored as TEXT** (not a JSON column), so cross-DB safe. `_parse_template` decides format: if `description` parses to a dict containing `"cells"`, it's the grid; otherwise it falls back to `columns_json`.
- **Real rows in the local DB (raw SQL):**
  ```
  id=1 name='invoice'    type='invoice' description=NULL columns_json=["invoice-number"]
  id=3 name='Template-1' type='invoice' description=NULL columns_json=[{name:Item,...},{Invoice Number},{Vendor name},{Total},{Item subtotal},{ID},{SKU},{GTIN}]
  id=4 name='Template-2' type='invoice' description=NULL columns_json=[{Item},{SKU},{GTIN},{Cost},{Item subtotal},{Subtotal}]
  ```
  **All three have `description = NULL`** → they are *legacy column-list* templates, **not grid templates**, and **none is a balance sheet**. No "BS Luq" template exists locally.

### A2 — Save path (`backend/app/api/routes/templates.py`)

- Endpoints: `POST /api/templates` (`create_template`, line 84) and `PUT /api/templates/{id}` (`update_template`, line 122).
- Frontend payload = `TemplateCreate`/`TemplateUpdate`: `{name, document_type, description, columns:[{name,type}], is_shared}`. The spreadsheet editor (`DocAgentSpreadsheet.tsx`) serializes the entire grid (`SheetSaveData`) to a JSON string and sends it as **`description`**.
- Backend processing before save (line 106-118): stores `description` **verbatim** (`description=payload.description`), builds `columns_json` from `payload.columns` with an `order` index, tags `client_id`. **No region analysis at save time** — the grid is stored raw and analyzed later, on every extraction.

### A3 — Read-back (`_parse_template`, `extract.py:257`)

`_parse_template(tpl)` → if `description` is a dict with `"cells"`, returns
`{mode:"layout", layout:<grid>, doc_type, name, regions:<_analyse_template_regions(grid)>}`.
The heavy lifting is `_analyse_template_regions` (line 375), which scans every cell and emits `kv_pairs`, `two_col_pairs`, `table_regions`, `explicit_targets`, `transposed_tables`, `section_label_rows`, `parallel_column_groups`, and a `primary_mode`.

**Real output of `_parse_template` on a representative balance-sheet grid** (cols A=asset labels/B=values, C=liability labels/D=values, 6 rows):
```
primary_mode: parallel_groups
needs_section_context: True
GROUP 1  label_col=A value_col=B   items: B1..B6  (Current Assets … Total Current Assets)
GROUP 2  label_col=C value_col=D   items: D1..D6  (Current Liabilities … Total Current Liabilities)
```
…**but it ALSO simultaneously produced** (see Part E for why this is the bug):
```
[REGION] 2 table(s) detected: ['Inventory', 'Prepaid Expenses']
[REGION] 1 transposed table(s) detected
[REGION] mode=mixed targets=0 kv=2 two_col=0 tables=2   ← computed "mixed" first, then overridden to parallel_groups
```

---

## 2. Gemini JSON structure (Part B)

### B1 — Exact prompt sent for the balance sheet

`_build_vision_prompt` returns `(system_instruction, user_prompt)`.
- **System instruction** = the `balance_sheet` persona from `prompt_registry.py` ("You are a chartered accountant…", full GAAP/IFRS line-item taxonomy) **+ injected "CRITICAL FINANCIAL ACCURACY RULE"** (because `needs_section_context=True`) **+ injected "PARALLEL COLUMN GROUPS RULE"**.
- **User prompt** (real, abridged — full text saved alongside this report in the run logs) contains, in order:
  1. `=== 2 PARALLEL COLUMN GROUPS ===` → tells Gemini to fill `[B1..B6]` for group 1, `[D1..D6]` for group 2, keyed by **cell reference**.
  2. `=== 2 TABLES ===` → **spurious**: "TABLE 1 'Inventory' columns [Prepaid Expenses, Deferred Revenue]", "TABLE 2 'Prepaid Expenses' columns [Total Current Assets, Total Current Liabilities]".
  3. `=== TRANSPOSED TABLE ===` → **spurious**: "return each column as a record".
  4. Universal rules, including **Rule 7: "Use the exact cell reference from the template (B3, D10) as the key in extracted_fields."**
  5. Self-verification steps.
  6. `=== DOCUMENT TEXT ===` (or "See document image" for vision).
  7. `=== OUTPUT FORMAT ===` (see B2).

### B2 — Exact JSON schema requested (`_build_output_format`, `extract.py:1745`)

For `primary_mode=parallel_groups` (n_tables=2) the code falls through to the **"form only"** branch and emits:
```json
Return ONLY valid JSON:
{ "document_type":"detected type","overall_confidence":"high","document_count":1,
  "documents":[{ "doc_index":0,"doc_hint":"brief description",
    "extracted_fields":{ "B3":{"value":"...","confidence":"high"},
                         "D3":{"value":"...","confidence":"high"} },
    "notes":"" }] }
RULES: extracted_fields keys MUST be cell references (B3, D10, …)
```
➡️ **The output schema has NO place for table_rows or transposed records**, yet the fields-description (B1.2/B1.3) told Gemini to extract two tables and a transposed table. **The instructions and the output schema contradict each other.**

### B3 — Real raw Gemini JSON from the last run (`backend/debug_output/last_extraction_raw.json`)

This file exists, but it is the **no-template (orchestrator) run on the income statement**, not a balance-sheet templated run:
```json
{ "provider":"GeminiClient", "model_used":"gemini-2.5-flash", "input_mode":"text", "success":true,
  "parsed_json": {
    "document_type":"other","overall_confidence":"high",
    "extracted_data":{
      "document_title":{"value":"Income Statement — Q4 2024","confidence":"high"},
      "date":{"value":"2024-12-31","confidence":"high"},
      "primary_entity":{"value":"Nexus Global Trading LLC","confidence":"high"},
      "summary":{"value":"…Net Revenue: $1,951,400 … Net Income After Tax: $266,538.","confidence":"high"} },
    "line_items":[], "metadata":{"currency_detected":"USD","language_detected":"en",…} } }
```
Where the raw response is captured: `LLMRouter.extract()` → temporary `_dump_raw_extraction()` hook (writes this file). It is **not** persisted to the DB (only `model_used`/`tokens_used` are).

### B4 — Structure of Gemini's JSON

There are **two different shapes**, depending on path:

**(a) Templated path** (`_build_output_format`): top-level `document_type`, `overall_confidence`, `documents:[{extracted_fields, table_rows / <section>_rows, notes}]`.
- Field values are referenced **by cell reference** (`"B2"`, `"D6"`) inside `extracted_fields`.
- Table rows: array of objects keyed by **column name**.
- Multi-section/multi-table: **separate array keys per table** (`earning_table_rows`, `deduction_table_rows`).
- Parallel-group balance sheets are *supposed* to come back as `extracted_fields` keyed by cell ref.

**(b) No-template / orchestrator path** (schema-driven, the B3 sample): top-level `extracted_data` keyed by **schema field NAME** (`document_title`, …), plus `line_items` + `metadata`. **No cell references.** This shape is exported via `_write_flat_table`, never the grid writers.

---

## 3. Excel writing trace (Part C)

### C1 — Every function that writes cells

| Function (extract.py) | Input | Writes | Cell decided by |
|---|---|---|---|
| `_write_excel` (5149) | doc_results, sheet_data(grid), regions | routes only | — |
| `_write_table_excel` (5176) | as above | template cells + one row per `table_rows` item | template `start_col + i`, `current_row++` |
| `_write_form_excel` (5225) | as above | template cells; fills `extractTarget`/empty value cells; dynamic pass | **`ref = f"{_col_letter(tc)}{tr+1}"` from grid position**, then `extracted_fields.get(ref)` |
| `_write_mixed_excel` (5476) | as above | form rows + table headers + data rows + dynamic pass | same `ref` from grid; table rows by column-name→`start_col+i` |
| `_write_flat_table` (5872) | doc_results | header row + one row per doc (no template) | column index by field name |
| helpers: `write_template_row` (5555), `write_table_data_rows` (5644), `_calculate_formula` (5422), `_adjust_formula_for_block` (5459), `_apply_cell_style` (5907) | | | |

Routing (`_write_excel`, 5163-5173): `table → _write_table_excel`, `mixed → _write_mixed_excel`, **everything else (incl. `parallel_groups`, `form_kv`, `form_with_targets`) → `_write_form_excel`.**

### C2 — Trace of one value: "Cash & Cash Equivalents = 168000" → cell B2

For a parallel-group balance sheet, the **pdfplumber-first path usually wins** (coverage ≥ 50%), so the trace is:
1. `_vision_extract_all_documents` (4253) → `_pdfplumber_spatial_extract` (3355).
2. Spatial: compute `value_col = label_col+1 = 1 (B)`; `col_x_band(1)` → an x-range derived from **template `colWidths`**.
3. For each PDF row, collect label words in col-A band + numeric words in col-B band. Match "Cash & Cash Equivalents" to the template item at row 1 (exact/Jaccard).
4. `cell_ref = _cell_ref(matched_row=1, value_col=1)` → **"B2"**; `extracted_fields["B2"] = {"value":"168000","confidence":"high"}` (3573-3574).
5. Merged into `_plumber_ef`, wrapped as `{"extracted_fields": …}` and passed to `_process_vision_result` (4381).
6. `_process_vision_result` normalizes + validates → saved `extracted_data["extracted_fields"]["B2"] = "168000"`.
7. Stored to DB `document_results.extraction_json`.
8. On export, `_write_form_excel`: iterating template cells, at grid `(tr=1,tc=1)` computes `ref="B2"`; cell is empty + `"B2" in extracted_fields` → writes `168000` to `ws.cell(row=2,column=2)` = **B2**. ✅

If instead the **LLM path** runs (coverage < 50%), step 4 is replaced by Gemini returning `extracted_fields` — and correctness depends entirely on Gemini actually using `"B2"` as the key (Rule 7).

### C3 — Where does "B2" come from in the writer?

**(b) Looked up from the template grid.** In `_write_form_excel:5270` and `write_template_row:5571`:
```python
ref = f"{_col_letter(tc)}{tr+1}"          # tr,tc = the template cell's grid row/col
filled = extracted_fields.get(ref) or label_to_value.get(tpl_value, "")
```
The target cell is the grid position itself; the value is whatever `extracted_fields[ref]` holds. The dynamic pass (5378, 5818) does the inverse: parses the **ref string from `extracted_fields` keys** back into `(row,col)` and writes there. So the writer is **driven by grid-derived refs**, and `extracted_fields` must be **keyed by those same refs**.

### C4 — Do prompt builder and writer share one source of truth for cell refs?

**Yes, for the ref *format/derivation*: both use the grid `(r,c)` via identical helpers.**
- Prompt builder: `_analyse_template_regions` sets `value_ref = _cell_ref(r, c+1)` (kv detection) and groups carry `value_ref` strings; `_build_fields_description` prints them as `[B2] = "label"`.
- Writer: `ref = f"{_col_letter(tc)}{tr+1}"`.
- `_cell_ref(r,c)` (974) ≡ `f"{_col_letter(c)}{r+1}"` (984) — **identical**.

**So the ref *system* is consistent.** The inconsistency is not in how B2 is spelled; it is in **whether the value-producer (Gemini, or the spatial extractor) actually populates `extracted_fields["B2"]` with the right value** — see Part E.

---

## 4. JSON persistence (Part D)

### D1 — What is saved, where (`_run_extraction_sync`, extract.py:4933-4951)

```python
doc = DocumentResult(
    job_id=job_id, filename=result.filename,
    document_type=…, overall_confidence=extracted.get("overall_confidence"),
    extraction_json = json.dumps(extracted, default=str) if extracted else None,   # ← PROCESSED result
    …, model_used=…, tokens_used=…, latency_ms=…)
```
- **Raw Gemini JSON: NOT saved to the DB.** It exists only transiently on `result.extraction_response` and (temporarily) in `debug_output/last_extraction_raw.json`.
- **Processed result IS saved** to **`document_results.extraction_json`** (TEXT column, accessed via `get_extracted_data()`/`set_extracted_data()`).

### D2 — Real saved rows (local DB, `document_results`)
```
doc 19 file='Invoice4.pdf' type='invoice' conf='high' json_len=2613
  TOP-LEVEL KEYS: ['document_type','overall_confidence','extracted_data','line_items','metadata']
  extracted_data: 6 entries — all {'value':'', 'confidence':'low'}  (Item, SKU, GTIN, Cost, …)
  table_rows: None
(doc 18, doc 17 identical structure, all-empty values)
```
These are **no-template/legacy-shape** rows (note `extracted_data` keyed by field name, plus `line_items`/`metadata`, and **no `extracted_fields`/`table_rows`**). They predate the grid pipeline and all have empty values — i.e. the local DB has **zero examples of a successful grid extraction**.

### D3 — "Download Excel" (`export_job_excel`, extract.py:5024; also `/export/zip`)

- **Reads from saved data — does NOT re-run extraction.** It queries `DocumentResult` rows, reloads the template grid from `ColumnTemplate.description`, re-runs `_analyse_template_regions` on it, and calls `_write_excel`.
- The field it reads: `doc.get_extracted_data()` → `extracted_data["extracted_fields"]`, `["extracted_data"]`, `["table_rows"]`, `["validation"]["confidence_map"]` (see `_write_form_excel:5245-5248`).
- ⚠️ Note: **template regions are recomputed at export time independently** of extraction time. They should match (same grid, same deterministic function), but it is a second invocation of the same buggy analyzer.

---

## 5. Mismatch diagnosis (Part E)

### E1 — Where the mapping breaks

There are **two independent break points**, plus a prompt-coherence defect that aggravates both. The *cell-ref system itself is consistent* (C4); the break is in **populating `extracted_fields` with correct ref→value pairs**.

**BREAK #1 — Spurious `table_regions` + `transposed_tables` on a parallel-group template ⇒ contradictory prompt.**
- **Function/line:** `_analyse_template_regions` (extract.py:375). It computes `table_regions` (line 519+), `transposed_tables` (687), and `parallel_column_groups` (761); then at **line 765** does `primary_mode = "parallel_groups"` **without clearing `table_regions`/`transposed_tables`**.
- **What it has vs should have:** `regions["table_regions"]` = 2 bogus tables and `regions["transposed_tables"]` = 1 bogus table; it **should be empty** when the grid is a pure parallel-group form.
- **Why it diverges:** the lower value rows (e.g. "Total Current Assets" + "Total Current Liabilities" on one row) look like a 2-cell "table header" to the table detector, and column A looks like row-labels to the transposed detector.
- **Effect on Gemini:** `_build_fields_description` (1452) emits the parallel-group block **and** a "2 TABLES" block **and** a "TRANSPOSED TABLE" block, while `_build_output_format` only provides an `extracted_fields` schema. Gemini receives 3 conflicting framings → it may return `table_rows`/nested objects (which the form writer ignores) or partially fill `extracted_fields` → **Column B/D end up empty**.

**BREAK #2 — Spatial extractor column geometry is guessed from the template, not the PDF.**
- **Function/line:** `_pdfplumber_spatial_extract` → `col_x_band` (extract.py:3416-3428):
  ```python
  x0 = sum(col_widths[:col_idx]) / total * pw   # template colWidths → PDF x-range
  x1 = sum(col_widths[:col_idx+1]) / total * pw
  ```
- **What it has vs should have:** it derives the PDF x-band for "value column B" from the **template's `colWidths` proportions**, which have **no relationship** to where the asset-value column actually sits in the source PDF. It should derive bands from the **PDF's own word x-clusters**.
- **Effect:** if the band misaligns, `words_in_band(vx0,vx1)` finds **no numeric words** → `extracted_fields["B*"]` never set → **Column B empty**; if it overlaps the *neighbouring* PDF column, group 1 captures group 2's numbers → **liabilities values land in the assets column** (and vice-versa).

### E2 — The balance-sheet failure specifically (B empty, liabilities misplaced)

- **What Gemini returned for Column B:** in the local environment this can't be shown (no BS template/PDF, and the pdfplumber-first path typically pre-empts the LLM). Mechanistically: when the prompt is self-contradictory (BREAK #1), Gemini tends to emit `table_rows`/section-nested objects instead of `extracted_fields["B2"…]`, so the form writer's `extracted_fields.get("B2")` returns nothing → **B blank**.
- **What the writer did with them:** `_write_form_excel`/`write_template_row` only fill a value cell when `ref in extracted_fields` (or a label match). Values returned under `table_rows` or under label keys are **never written to B/D** → those columns stay empty; any value the writer *does* find via the wrong band (BREAK #2) is written to whatever grid cell the ref names → liabilities numbers in the assets column.
- **Where they ended up instead:** either dropped entirely (left in `table_rows`, which the form writer ignores), or written to the wrong column because the spatial band matched the wrong PDF column.

### E3 — All places the mismatch can occur
1. **`_analyse_template_regions`** — spurious tables/transposed not cleared for `parallel_groups` (prompt incoherence). *(extract.py:765, 519, 687)*
2. **`_pdfplumber_spatial_extract.col_x_band`** — template-geometry x-bands vs real PDF columns. *(3416)*
3. **`_pdfplumber_extract_dynamic_parallel`** / `_pdfplumber_extract_form_fields` — text-mode fallbacks with their own label-matching that can mis-key. *(3671 / 4075)*
4. **LLM ref-keying reliance** — writer assumes Gemini keys `extracted_fields` by exact cell ref; if Gemini uses label/nested keys, lookups miss. *(no schema enforcement between prompt and `extracted_fields.get(ref)`)*
5. **Double analysis** — regions recomputed independently at extraction time and again at export time; both run the same buggy analyzer. *(extract.py:271 vs 5057)*

---

## 6. Full picture (Part F)

### F1 — Data flow diagram
```
TEMPLATE SAVE
  DocAgentSpreadsheet.tsx  → SheetSaveData(JSON)
  POST/PUT /api/templates (templates.py:84/122)
  → ColumnTemplate.description = <grid JSON>           [DB: column_templates.description, TEXT]
                                   (no analysis at save time)

EXTRACTION  (background thread, extract.py:4792)
  preprocess_file (preprocessor.py)  → text (pdfplumber) + page images (pdf2image)
  _parse_template (257) → _analyse_template_regions (375)
        └─ derives cell refs via _cell_ref()   ← REF SOURCE OF TRUTH #1
        └─ BUG: parallel_groups + spurious table_regions + transposed_tables coexist
  _vision_extract_all_documents (4253)
     ├─ pdfplumber-first (coverage≥50%):
     │     _pdfplumber_spatial_extract (3355)  → extracted_fields keyed _cell_ref(row, value_col)
     │            col_x_band (3416)  ← BUG: template colWidths used as PDF geometry
     │     _pdfplumber_extract_dynamic_parallel (3671) / _extract_form_fields (4075)
     └─ else LLM:
           _build_vision_prompt (1229) → Gemini (gemini_client.extract_data*)
                 prompt tells Gemini to key extracted_fields by _cell_ref  ← REF SOURCE OF TRUTH #2 (same fn)
           LLMRouter.extract (llm_router.py)  →  [TEMP] _dump_raw_extraction → debug_output/last_extraction_raw.json
  _process_vision_result (2601): _fix_split_decimals→_normalize→_validate_with_pdfplumber
     → extracted_data{ extracted_fields:{ref:val}, extracted_data:{label:val}, table_rows:[], validation:{} }
  SAVE  (4933): json.dumps(extracted) → [DB: document_results.extraction_json, TEXT]   (RAW Gemini NOT saved)

DOWNLOAD EXCEL  (export_job_excel 5024)   — reads saved data, NO re-extraction
  reload ColumnTemplate.description → _analyse_template_regions AGAIN (5057)   ← buggy analyzer runs twice
  _write_excel (5149) routes by primary_mode →
     _write_form_excel (5225) / _write_mixed_excel (5476) / _write_table_excel (5176)
        ref = f"{_col_letter(tc)}{tr+1}"   ← REF SOURCE OF TRUTH #3 (same derivation)
        cell value = extracted_fields.get(ref)   ← fails if extracted_fields not keyed by that ref
```

### F2 — Simplest fix to make prompt/writer refs consistent
The ref *spelling* is already consistent (all three derive from the grid via `_cell_ref`). The cheapest high-impact fix is **prompt coherence**: when `parallel_column_groups` is detected (or `primary_mode` is set to `parallel_groups`), **clear `regions["table_regions"]` and `regions["transposed_tables"]`** (and skip their blocks in `_build_fields_description`). That removes the contradictory "2 TABLES / TRANSPOSED TABLE" instructions so Gemini is told exactly one thing — fill `extracted_fields` by cell ref — matching the output schema and the writer. One small guard in `_analyse_template_regions` around line 765 (plus mirroring it at export-time analysis).

### F3 — Persisting raw JSON for direct Excel writing
Add a column (e.g. `document_results.raw_llm_json TEXT`) and write `result.extraction_response.raw_text`/`parsed_json` in `_run_extraction_sync` (additive migration, fits the `ADD COLUMN IF NOT EXISTS` startup pattern). Then the export path could read a **pre-computed, frozen ref→value map** instead of re-deriving regions at export time (eliminating BREAK #5 and making downloads reproducible). To use it *directly* for Excel writing, also persist the resolved `{cell_ref: value, confidence}` map (it already exists as `extracted_fields`) and have `_write_*` consume that map exclusively, rather than re-analyzing the grid.

---

## Summary

**The extraction display is failing because** the value-producers do not reliably populate `extracted_fields` with the grid-derived cell refs the Excel writer looks up. Two concrete causes: (1) `_analyse_template_regions` (extract.py:375/765) leaves **spurious `table_regions` and `transposed_tables` populated on parallel-column balance sheets**, so `_build_vision_prompt`/`_build_fields_description` send Gemini three contradictory framings (fill cells *and* extract two tables *and* transpose) while the output schema only allows `extracted_fields` — Gemini then returns table/nested JSON that the form writer ignores, leaving Column B/D empty; and (2) `_pdfplumber_spatial_extract.col_x_band` (extract.py:3416) computes each value column's PDF x-band from the **template's `colWidths`** rather than the PDF's real column positions, so values are missed (empty B) or captured from the neighbouring column (liabilities in the wrong column). **The fix is** to make the region analyzer mode-exclusive — when `parallel_groups` is detected, clear/suppress `table_regions` and `transposed_tables` so the prompt and output schema agree — and to derive the spatial extractor's value-column bands from the PDF's own word x-clusters instead of template widths (and, longer-term, persist the resolved `extracted_fields` map and reuse it at export time instead of re-analyzing). **It touches** `backend/app/api/routes/extract.py` — `_analyse_template_regions` (≈line 765 + the table/transposed blocks 519/687), `_build_fields_description` (1452) and `_build_vision_prompt` (1229), `_pdfplumber_spatial_extract`/`col_x_band` (3355/3416), the export-time re-analysis in `export_job_excel` (5057), and optionally `_run_extraction_sync` (4933) + a `document_results` column for raw-JSON persistence.
