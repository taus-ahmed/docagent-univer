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

`tests/gold/hand_drawn/` holds five templates saved the way the EDITOR saves
them — only cells a person typed, no styling and no markers. The nine in
`tests/gold/templates/` came from the old `extractTarget` tool, which
materialised an explicit empty cell for every slot, and both fixtures in
`tests/fixtures/prod_templates/` work because someone dragged a border over the
value column (`bank_statement_101`: 29 explicit-empty cells, all 29 styled). So
the committed corpus satisfied a precondition the editor never satisfies, and
the harness could read 98.5% while everything drawn by hand scored zero slots.
Score across R1–R3: 4/15 → 11/15 → 13/15 → **15/15**.

`tests/fixtures/scenarios/` holds six SCENARIO fixtures — the shapes the gold
corpus cannot see: grouped rows in one band, wrapped cell values, selection
markers printed in the text, a selection state absent from the text, no-invention
against semantic matching in one document, and several documents in one file.
They are scored by `tests/harness/scenarios.py` and asserted by
`tests/test_scenarios.py`, and are **deliberately not wired into the main
harness** — folding them into the gold set would move the headline accuracy
number and make it incomparable with every figure recorded before, while mixing
"how well does it do the things it does" with "does it do these things at all".

`tests/test_protected_behaviours.py` pins the nine behaviours the defect
analysis lists as already correct, written against the CONTRACT AS IT NOW IS
rather than as observed — pinning the old behaviour would have frozen two
defects in place.

`pytest.ini` deselects `-m live` by default. `-m known_bug` marks a reproduction of an
unfixed bug; those are additionally `xfail(strict=True)`, so the default suite
stays green AND the marker cannot go stale — the day the fix lands, the
unexpected pass is reported as a FAILURE and forces the marker off. Two are
open: `multi_document` and `selection_no_marker_in_text`. The old
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
| `backend/engine/text_layer.py` | 470 | positional evidence: words with x/y; wrapped-value repair; column bands; placement; record spans; AcroForm state |
| `backend/engine/doc_boundaries.py` | 170 | one file → many documents, deterministically |
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

**"Empty" means empty, not absent-from-the-dict (R1).** The editor saves a
SPARSE grid — `applyStyle` writes an entry for every cell in the selection, and
nothing writes one for a cell you leave alone — so presence in `grid["cells"]`
was an artefact of bookkeeping, and *drawing a border was what made a template
extractable*. `_used_range` is the bounding box of cells carrying **text**
(widened to cover declared regions and merges); inside it, absent and empty are
the same thing. **Styling deliberately does not extend the box.** A one-column
box is widened by one, because a label column implies a value column and nothing
else explains a template that is only labels.

**Merges come from `grid["merges"]` (R4).** A covered cell is neither label nor
slot but part of its parent, so a heading merged across `A1:E1` cannot mint a
phantom slot. Per-cell `mergeParent`/`mergeSpan` are still *read* for grids
saved by older editors and are no longer *written* — `bank_statement_101`
carries them under one of its two merges and not the other, which is why the
top-level list has to be the authority.

`compute_shape(grid)` returns:

```python
{"version": 1,
 "header_rows": [9], "label_columns": [0], "value_columns": [1],
 "repeat_bands": [{name, header_row, start_row, end_row, columns, section}],
 "field_slots": [{slot_id, ref, row, col, row_label, col_header, section}],
 "required_columns": 6,        # the widest band — what a path must serve
 "coverage": {...},            # R6, below
 "summary": "…"}               # human line, computed HERE, never in TypeScript
```

**Bands.** A repeating band is **≥2 adjacent static cells with empty rows
beneath**; a two-column band is a label/value pair by construction; a band at
the very bottom of the grid with ≥3 columns is treated as a band and expanded by
the writer, while 2 columns stays ambiguous and is **skipped out loud**.

A band **ends (R3)** at the first row below its header that either fills at
least **half** its columns (a row of the band's own shape) or is **trailing** —
no blank row follows it before the span ends. Anything else, with the table
continuing blank beneath, is a row label *inside* the band. The old rule was
"the first row holding ANY static cell", so one typed `Subtotal` turned a ten-row
table into a three-row band. Both halves are load-bearing: HALF, not "all but
one", because `bs_luq` is two label/value pairs side by side whose totals row
fills 2 of 4; TRAILING, because the gold bank statement's three summary lines
under a six-column table are 1-of-6 each and FULL alone swallowed them.

**Field slots are decided by COLUMN ROLE (R2), not a left-to-right scan.**
Within a block of consecutive rows, a column is a *label column* if some body
row has text in it, and a *value column* if none does. A value column becomes a
slot on every row whose paired label holds text, addressed
`(row_label, col_header)`. Three constraints, each of which a real template
found:

- **A value column must be justified** — named by the block's heading row, or
  immediately right of a label column. The gold invoice's key/value block spans
  A–E because the table below is five wide; unjustified, each of its nine labels
  would sprout four slots.
- **The owner is fixed by geometry** — the nearest label column to the left,
  which must then hold text on that row. Searching further left for a filled one
  hands column D to `Acct Type` and invents a value the row does not have.
- **A block's heading row** is its first row when it has text in strictly more
  columns than any row beneath it. That is the matrix signature (3, then 1s) and
  does not fire on a key/value list (1, then 1s).

The old scan made a slot immediately right of a static cell and then stepped
*past* it, so a matrix lost every value column after the first — four slots
where eight were drawn, no error, a half-filled sheet that looked like it worked.

**A field slot has no detectable section.** `_section_for` answers "is the line
above a title", which only means something when the line below is a band header.
Asked about an ordinary field it returns the previous field's label, and that
reached the model in every slot prompt. A section title is either **merged
across columns** (unambiguous by geometry, so blank rows between it and its table
do not matter) or **a lone static on the line directly above**; a row that titles
a band is not also a field in it.

### R6 — coverage: what the engine understood, and what it left behind

`is_usable` answers one bit, and a template can be badly wrong while passing it.
`shape["coverage"]` carries `labels`, `labels_with_slots`, `orphan_labels`,
`field_slots`, `band_cells`, `skipped` and `complete`.

It measures **labels, not empty cells** — counting unclaimed cells reads alarm
into ordinary templates, since three of the gold invoice's columns are
legitimately blank forever. Band headers, band interiors, section titles and a
block's own heading row are excluded: they are labels doing a different job.
`skipped` holds only what the engine **refused** (`_skip`), never what it
narrates (`_say`) — "declared TRANSPOSED table: …" is a success.

`POST /api/templates/shape` returns `coverage`, `usable` and the engine's own
`error`. **The editor blocks a save the engine cannot act on and warns on a
partial one**, using those values rather than re-deriving the rule in
TypeScript. Partial coverage warns and proceeds — a notes column the engine will
never fill is a legitimate thing to draw.

**`coverage` measures labels, which is no question at all for a pure table.** A
template that is only a declared band has no labels waiting for slots, so it
reported `labels: 0, complete: True` and the gate had nothing to say however
wrong the table was. All 23 real templates in the repo report complete — and so
did four deliberately broken ones. `_gate_findings` adds `coverage["warnings"]`
and `coverage["blocking"]`:

| rule | false positives | verdict |
|---|---|---|
| **A** a band column with no heading | 0/23 | **warn** — the only rule that catches a blank top-left corner (D12a), which a user cannot diagnose from the editor |
| **D** a band with NO headings at all | 0/23 | **block** — a severity split on A, not a separate detector |
| **E** two declared regions overlapping | 0/23 | **warn** |
| ~~G~~ duplicate headings in a band | **1/23** | **rejected** — fires on `bs_luq`, a real production template laying two label/value pairs side by side under two `Amount` columns, which the engine already disambiguates by column letter |

Each rule was chosen on its false-positive rate, because a gate that fires on a
legitimate template is the same class of bug as the silent failure it replaces.
A warns rather than blocks because 23 templates is evidence, not proof, and
every one of them was drawn by us — the shapes a real user draws are the ones
not in that sample. **`is_usable` is unchanged**: it asks whether there is
anywhere to put anything, and a headless band has plenty of cells, so blocking
is its own list rather than an overload of that bit.

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

**A declared table needs two columns, in both orientations (R5).** The rows
branch tested `c2 < c1`, true only for a region of NEGATIVE width, so a
one-column region passed and built a single unnamed value column with no label
column to anchor it — the model was asked for one value per row with nothing
saying what the value was, and returned cover-page text. The transposed branch
had always checked `c2 <= c1`. A refused region is reported in
`coverage["skipped"]`, not just logged.

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

**A row is identified by WHICH LINE it was read from, not by what that line
says.** Identity used to be the TEXT of the source span, dropping every later
row that quoted the same words — correct only if the document prints those words
once. Two rows legitimately quoting one line is ordinary (a group header, a
repeated column heading, a document that prints a line twice) and *structural*
in the case this product exists for: five merged invoices repeat 9 lines and
make 33 rows deletable; five payslips, 11 and 43 (`Description Amount` ×10).
Linear in the number of documents in the file.

Each row now claims one **occurrence** of its source line
(`text_layer.source_occurrences`, exact line match preferred over a fragment
match, multi-line quotes matched on their first line). A row that can claim a
free occurrence is real, however many others quote the same text. Only a row
claiming a line every copy of which is already spoken for is a duplicate —
which *is* the fabricated-row case, stated precisely instead of approximately.
Without geometry (the image path, callers passing no `page_lines`) identity
falls back to the source **plus the row's own values**, so two different rows on
one quoted line still both survive; that fallback cannot catch a hallucinated
variant of a real row, which is why `page_lines` is worth threading through.

**A dropped row is visible.** It appeared only in `validation_notes` — not
flagged, not in `needs_review`, not in the confidence map, invisible in the app
and in the export. It now raises a `flagged_fields` entry **carrying the row's
own content**, sets `needs_review`, and increments
`validation.dropped_row_count`. A silent deletion is worse than a duplicate row,
because nothing tells the reader to go and look. It is deliberately *not* put in
the export: the export is the file the client works in, and a row the engine
believes is fabricated does not belong in it.

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

### One file can be many documents (`engine/doc_boundaries.py`)

One file was one document, unconditionally. Three invoices merged into one PDF
gave **13 field slots where 3 × 13 were needed** — a single slot addressed
"Invoice Number" against three distinct invoice numbers — and the two the model
did not answer for were lost with no error, no flag and no note. That is the
product's own core use case.

`run_extraction` splits the file and runs the ordinary pipeline once per
document. **Slot addressing is unchanged**: each document gets the full slot
set, its own grounding, its own confidence and its own result, and the Excel
writer already stacks a list of results. Cost scales linearly, which is honest —
twenty invoices is twenty documents of work.

**A repeated title means "a new document" in a concatenation and "a
continuation" in a form, and it is the same observation in both.** Treating it
as sufficient cut a six-page Closing Disclosure in two and lost its entire
Contact Information page — five parties by nine rows — because the second block
was asked for the first page's slots. Signals are now ranked:

| | signal | role |
|---|---|---|
| suggests | **repeated title** — within a run of same-type pages, that run's first line, or a line on two CONSECUTIVE pages | a candidate, never a verdict |
| decides | **type change** — a page classifying differently from the last page that classified at all | 0 of 17 multi-page corpus documents change type, so no corroboration is required — and requiring it cost a real boundary, since an invoice and the cheque paying it share the PO they both quote |
| corroborates | **the reference changes** | recurrence means CONTINUATION. A CD repeats `Loan ID # 123456789` on every page; twenty invoices carry twenty numbers. The old rule had this backwards |
| vetoes | **"page 3 of 5" after "page 2 of 5"** | per RUN, so a stack of forms still splits. Load-bearing on the real CD, whose page 4 reads as a bank statement and page 6 as a tax form |
| overrides | **"page 1 of N" after a later page** | the one boundary allowed on no other evidence — two copies of one form share every reference |

Measured: **0 false positives across all 60 corpus documents** (17 of them
multi-page), and **14 of 14 merged files split at exactly the right pages** —
twenty invoices, five two-page payslips, mixed batches with runs inside them.

Three details each fix a real miss:
- **Adjacency** is what tells a title from a repeated footer. Two income
  statements give `[title, "Prepared by…", title, "Prepared by…"]` and *both*
  lines repeat; only the title opens its segment and neither is adjacent to
  itself.
- **Anchoring per segment**, not to page 0, finds two receipts in the middle of
  a mixed batch — they classify as `None`, so the type never changes.
- **The type is compared to the last KNOWN type**, because a continuation page
  often classifies as nothing and letting that erase the segment's type hid the
  next document's start entirely.
- A candidate whose document would be **page furniture is folded into the one
  above** rather than abandoning the whole split.

⚠ **The costs are asymmetric the other way round from what was first assumed.**
Over-splitting loses everything on the split pages *silently*, because the slots
asked for belong to a different page. Under-splitting returns one document where
there were several, which is visible. The rule now under-splits by construction,
and the case it gives up is recorded: **a concatenation whose documents carry no
readable reference is treated as one document.** Falling back to the title rule
there was considered and rejected — it reintroduces guessing exactly where there
is least information to justify it.

### A record is not a line

A row's cells were verified against the ONE line the model quoted, which is
right for a table and wrong for a form. `FORM-W2-2023` lays each employee across
four printed lines, the model quotes the first two, and the values on the others
were reported ungrounded — correct, and marked `low`. `record_span` runs from
the line this row was read from to the line the NEXT row was read from, so a
cell can be checked against its own record and **can never reach into a
neighbouring one**. Capped at 8 lines.

### Selection state (D7)

A field offering options is only answerable if something says which is chosen.
Three cases, and they are not the same:

| the marker is… | behaviour |
|---|---|
| **printed** (`[X]` / `[ ]`) | correct — 9/9, not one unselected option reported |
| **an AcroForm widget** | **recovered from the file.** `acroform_widgets` reads `/AS` (falling back to `/V`) off every `/FT /Btn` widget and `inject_markers` writes `[X]`/`[ ]` into the text at the widget's own x, so it lands before its option. 8/8 |
| **neither** (flattened/scanned; the tick is vector graphics) | **not recoverable.** A prompt rule takes it from 3/7 to 6/7 and costs nothing elsewhere, but a prompt rule is a request, not a guarantee |

Before this, a widget-checkbox form had its selection state invented for every
option field at `high` confidence with `needs_review=False` — answering
`Services` where the form says `Wholesale trade`. Every option is printed on the
page, so grounding confirms whichever one is picked. These are the fields that
decide treatment.

Zero of the 60 corpus PDFs carry AcroForm fields, so the fixture is built by
`tests/fixtures/make_fillable_form.py` — committed as a script as well as a PDF
so it can be read and argued with.

### The text layer carries geometry, not just characters (`engine/text_layer.py`)

`page.extract_text()` returns a flat string, and everything downstream — the
prompt, grounding, the confidence vocabulary — saw a document with no geometry
in it. Two defect classes follow directly, and neither is visible in the output.

**Wrapped values.** A PDF that renders a figure inside a narrow box wraps it
like any other text, so the page really does print `$1,268.7` on one line and
`5` on the next. `extract_words()` agrees: **the split is in the file, not in
the reader.** The model is handed `$1,268.7`, answers `5` for the next slot, and
both halves ground perfectly because both halves are genuinely printed. On
`FORM-W2-2023.pdf` this returned **11 wrong values out of 12, every one marked
`high`, while the single correct value was the only one marked `low`** — the
confidence signal exactly inverted. `_fix_cross_page_decimals` was a string-level
patch for one instance of this; the general case needs geometry.

A fragment is fused only when it is on the immediately following line, sits
inside its parent's horizontal span, shares its parent's right edge to within
1pt, and **completes the parent exactly**. `_shortfall` is the whole safety
argument: only three shapes are incomplete —

| parent | missing |
|---|---|
| `14,210.` | a bare decimal point → exactly 2 digits |
| `1,268.7` | one decimal digit → exactly 1 |
| `144,58` | a final comma group of 1–2 digits → the rest, optionally with cents |

**A complete number is never repaired**, so two Balances stacked in a
right-aligned column — identical right edges by construction — cannot be fused
into each other. **A bare integer is never incomplete**: nothing in `18` says it
was cut short, so `18` over `000` stays two numbers. A missed repair is a
visible wrong value; a false repair invents a figure, which is worse.

⚠ **Lines are clustered on the gap between tops, never bucketed on `top / tol`.**
Bucketing splits any line straddling a bucket edge — on the W-2 it broke one
printed line in two, put a fragment two lines below its parent, and lost 4 of
20 repairs.

⚠ **A page needing no repair is returned from `extract_text()` VERBATIM.**
Rebuilding word lists into text is not byte-identical — 30 of the corpus's 77
pages differ in whitespace — and the text is part of the prompt, so rewriting
untouched pages would change what the model is asked and invalidate its cached
answer for nothing. Only pages that genuinely need repair are rebuilt. In the
60-document corpus that is 6 documents, 25 repairs.

**Placement (D6).** Grounding answers "is this value in the document". It cannot
answer "does this value belong in THIS column", because a flattened line has no
columns — which is why a Debit written into the Credit column quoted the same
source line and passed every check at `high`. `column_bands` reads the x-span of
each heading off **the document's own heading line**; `check_placement` passes a
value whose right edge is flush with its column (money columns are right-aligned
and hold to well under a point) or whose span overlaps it (left-aligned text).
Anything else is demoted to `low` and flagged with **the column it actually sits
under**.

The check is **opportunistic on purpose**: a band whose headings the document
does not print gets no bands and no verdict, and a caller passing no
`page_lines` behaves exactly as before. Calling a placement wrong on a guessed
column would demote correct values, which is the failure it exists to prevent.

**A misplaced value is kept, not dropped** — trading a visible wrong cell for an
invisible missing one is not an improvement.

### One join rule for a multi-line value (D9)

**A field's value is the document's own words, in reading order, joined by a
single space.** The join used to be whatever the model returned, and it returned
three different things for ONE field on ONE document — `INV-2024-0031`'s Notes
came back truncated at the first line, joined with a literal newline, and joined
with a space, across cached runs; adjacent fields disagreed inside one run. The
words are at known positions, so `canonical_value` re-derives the join instead
of trusting the string.

**Nothing is added and nothing is dropped.** The run of words must spell exactly
what the model claimed, ignoring whitespace; a value matching no run is returned
unchanged, which is what happens to anything derived or renotated (a MICR field,
a reformatted number).

**A value continues onto the next line only inside its own column block.**
Reading order interleaves side-by-side columns — on that invoice, the word after
`Ref:` is the LEFT column's `ABA:`, not this value's own continuation — so the
walk steps over anything outside the run's horizontal span.

**Across a line break, a space only when the seam is not mid-token.** Joining
everything with a space is right within a line and wrong across one: a PDF wraps
`joesmith@ficusbank.com` into two fragments, and gluing those with a space
produced `sarah@ epsilontitle.com` — an address that looks ordinary in a
spreadsheet and bounces when anyone uses it, which is the exact failure class the
text layer exists to remove, reintroduced by its own repair. `_joiner` gives no
space when the fragment ends `@ / - \ _`, when the next begins `@`, or when it
ends `.` and the next starts lowercase (`ficusbank.` + `com`); a `.` before a
capital keeps its space, so `123 Commerce Pl.` + `Somecity` is safe.

**The gutter is measured from the PAGE.** A fixed threshold cannot work —
`INV-2024-0031`'s note columns sit 122 pt apart, the Closing Disclosure's
five-party contact matrix packs its columns 10–26 pt apart, and 24 pt read that
matrix as one continuous line. Per LINE fails too, and instructively: on a row of
one-word cells (five email addresses) *every* gap is a gutter, so the line's own
median gap is one. The page is the right scale, because the ordinary gap between
two words of a phrase is a font property (1.5–2.6 pt on both documents) and most
gaps on a page are of that kind. `gutter_for_page` = `max(6, 4 × median gap)`.

**The in-column reading is tried first.** `_walk` runs twice: once stepping over
same-line words beyond a gutter, once allowing the crossing. That is what lets an
email in the third column of a contact matrix find its own continuation on the
next line instead of swallowing the fourth column's, and it means the merged-
columns flag now fires only when there is no in-column reading at all. A merged
value is still kept, marked `low` and flagged — which half was wanted is not
knowable.

> **A field does not absorb the next line just because one is there.** Whether a
> name field should take its address is a design question and this is the
> answer: no. Absorbing is how one field swallows another's value, and a short
> value is a visible fault where a swallowed one is not. Truncation therefore
> stays a model behaviour rather than being papered over.

### The export carries the look, not just the values (D13)

`_write_slot_excel` wrote values and nothing else, so merges, centring, shading
and borders were in the editor and absent from the file. **`_apply_cell_style`
already existed and four legacy writers called it** — the slot writer simply
never did, so this is a reuse rather than a new implementation, and there is
still exactly one place that knows the editor's `CellStyle`.

- **Style travels with a cell whether or not it holds text.** A bordered empty
  value cell is a box the user drew, and it is precisely the cells *without*
  text that the slots fill.
- **A merge widens the writer's extent.** `_find_template_dimensions` counts
  content cells, and a heading merged across A:D has content only in A, so the
  range fell outside the sheet and was dropped. `template_shape._used_range`
  already widened for merges on the shape side; the writer now does the same.
- ⚠ **A merge crossing a band is SKIPPED.** The writer expands a band to the
  document's row count, so the cells the range used to cover are not the cells
  it would cover now, and a merge landing on the wrong rows hides real values
  behind a heading.

### Every written column gets a width (D14)

Widths were applied **before** the writer ran, across
`_find_template_dimensions` — which counts only cells carrying TEXT. Under the
one rule a value column carries no text, so the extent was routinely narrower
than the sheet the writer then filled, and every column past it got no width and
fell back to Excel's 8.43, truncating extracted values and the user's own
labels. Which columns that hit depended on where the template happened to have
headings, which is why it looked like auto-fit applying on some runs and not
others.

`_fit_columns` runs **after** the writer, when `ws.max_column` is the real
extent. A width the user dragged wins as given; a column without one is fitted
to its longest cell and clamped to 8–60 characters — the clamp stops one long
note dominating a sheet nobody sized, and deliberately does not apply to an
explicit choice.

### Export keeps the notation as well as the number (D8)

`coerce_cell_value` writes money as a **number** so the cell sums and sorts;
that is right, and it is also why the export lost the currency symbol and the
trailing cents. `cell_format` derives an Excel number format **from the source
string**, so the cell holds `7750.0` and reads `$7,750.00`, and a multi-currency
document keeps the symbol printed on each line rather than one chosen globally.
Accounting parentheses survive as `#,##0.00_);(#,##0.00)`. An identifier held as
text gets no format — a routing number is not a quantity.

The **stored** value was always the verbatim string and always did appear in the
document: the grounding chain was never broken, only the presentation. This is
one function at the export boundary, not a validation change.

### Result contract (`DocumentExtractionResult.extracted_data`)

```python
{"document_type", "overall_confidence", "extraction_method": "slot_directed",
 "extracted_fields": {cell_ref: value},          # what the writer places
 "extracted_data":   {row_label: {value, confidence, ref}},
 "slot_map": {"fields": [...], "tables": [...]}, # geometry for the writer
 "<band name>_rows": [ {col_key: value, "_confidence": "high"} ],
 "validation": {flagged_count, flagged_fields, confidence_map,
                ungrounded_count, misplaced_count, dropped_row_count,
                low_confidence_ratio,
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
| **accuracy** (container-aware headline) | **98.7%** | **98.2%** |
| **content** (container-blind) | 97.9% | 97.1% |
| **structure fidelity** | **100%** (17/17) | **100%** (17/17) |
| accuracy RAW (all adapter widenings off) | 48.0% | 71.1% |
| invented (value nowhere in the PDF) | **0** | **0** |
| misfiled | 4 | **0** |
| out-of-schema (*not* a defect) | 0 | 60 |
| **defect rate** | 1.0% | **0.0%** |
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

**The cell's LABEL decides what a digit run is.** `NMLS ID 222222` exported as
`222222.0`: six digits, no leading zero, so no rule about the *shape* of the
digits could save it — 222222 is a perfectly ordinary number. The column is
headed `NMLS ID`, and that is evidence the value does not carry.
`labels_an_identifier` matches identifier words (`id`, `no`, `number`, `#`,
`code`, `ref`, `nmls`, `ein`, `ssn`, `routing`, `account`, `licence`, `policy`,
`zip`, `phone`, …) as whole words, so `Paid` does not contain `id`.

⚠ **Quantity words WIN over identifier words**, because the overlap is real and
always resolves the same way: `Account Balance` and `Invoice Total` are money,
`Account No` and `Invoice Number` are not. A rule that turns quantities into text
is the mirror-image failure and breaks every sum in the sheet — a `Qty` of 40
stays a number.

**What it still costs:** a 6–8 digit identifier in a cell whose label says
nothing is read as a number. The label is the only evidence there is, and
without it `222222` is just a number. Leading zeros and runs of 9+ digits are
still caught by shape alone.

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

Startup order: `init_db()` → `_run_migrations()` → `ensure_storage_dirs()` →
`_seed_admin()` → `_seed_demo_schema()` → `_materialise_schemas()` →
`_release_stranded_jobs()`.

⚠ **`_release_stranded_jobs()` fails any job left `pending`/`processing`.**
Extraction runs on a daemon thread, so it dies with the process — a deploy, a
restart, an OOM kill — and the job row stayed `processing` for ever while the UI
polled it every two seconds. A hung job is worse than a failed one: a failed one
can be retried. Boot is the one moment the answer is certain, because this
process owns no threads yet, so no age threshold is needed or used. **This
assumes ONE instance.** Phase 4 moves extraction to Celery, where the queue owns
liveness; anyone scaling past one worker must rework this in the same commit.

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
- **A grid from the editor is SPARSE.** Only cells that were typed, styled, merged or pasted are in `grid["cells"]`. Never treat presence as meaning — use `_used_range`.
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
