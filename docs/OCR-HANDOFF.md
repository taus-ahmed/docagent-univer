# OCR — context handoff for a new session

Written 2026-09-16 at `2b9f6ba`, after round 2 closed. Read
`CLAUDE.md` first; this is the part that is not in it.

---

## 1. The product, the stack, where it runs

DocAgent v2.0 is a multi-tenant document-extraction SaaS. A PDF is uploaded, a
spreadsheet template's cells are enumerated as addressed slots, Gemini fills
each slot and quotes the span it read it from, the spans are verified against
pdfplumber text, and the result is written back into the template as Excel.
Multi-tenant with `client_id` on every data table, JWT auth, PostgreSQL.

| | |
|---|---|
| backend | FastAPI + SQLAlchemy 2.0, Python 3.11, `backend/` |
| frontend | Next.js 14 App Router, `frontend/` |
| database | PostgreSQL (SQLite dev fallback) |
| model | `gemini-2.5-flash-lite` in production; the harness pins the same |
| storage | `STORAGE_BACKEND=local` today; S3/R2 wired and tested, not switched on |
| backend deploy | Railway, auto-deploys from `main` |
| frontend deploy | Vercel, auto-deploys from `main` |
| production | `https://loving-grace-production.up.railway.app` |
| repo | `E:\docagent-univer` |
| branch | **`main`**. Not `feat/accuracy-harness` — a fully-merged ancestor last touched 2026-08-24; checking it out silently reverts everything since |

Extraction runs on a daemon thread inside the web process. Phase 4 moves it to
Celery. `main.py::_release_stranded_jobs()` fails any job left `pending` or
`processing` at boot, and **that assumes one instance** — anyone scaling past
one worker must rework it in the same commit.

---

## 2. Current numbers, and what they describe

Replay at `591d3b6`, `tests/reports/latest*.json`:

| | templated | no-template |
|---|---|---|
| accuracy (container-aware headline) | **97.2%** | **96.7%** |
| content (container-blind) | 96.7% | 95.9% |
| structure fidelity | 100% (17/17) | 100% (17/17) |
| invented (value nowhere in the PDF) | 0 | 0 |
| misfiled | 4 | 0 |
| defect rate | 1.0% | 0.0% |

Suite: **1034 passed, 4 xfailed, 1 deselected** (`-m live` is deselected by
default). The four xfails are deliberate `known_bug` reproductions, each
`xfail(strict=True)` so the marker cannot go stale: the `selection_no_marker_in_text`
scenario, round 2's absent-field answer, and the combined / per-file exports
writing no table rows (two entries).

**What corpus those numbers describe, precisely:**

- **10 gold-labelled documents** (`tests/gold/labels/`), 9 templates, 115 field
  slots, 89 table rows, 277 table cells. All ten are **in-house fixtures we
  drew ourselves**. Mean document text is ~248 tokens — one to two pages.
- **69 PDFs** under `tests/test_pdfs/`, used for boundary detection, text-layer
  and regression work. 61 are in-house; 8 are the round-2 files.
- **The round-2 files are the only real-world documents in the repo**:
  `SampleBill.pdf` (an ENGIE utility bill), `HTR-043235.pdf` (a Bank of America
  statement, duplicated), `feb2225.pdf` (a Berkshire earnings release),
  `bank-statement-sample.pdf`, and three CFPB mortgage forms. Four of them —
  the ENGIE bill, the BoA statement, the Berkshire release and the CFPB Closing
  Disclosure — carry essentially all of the round-2 evidence.

**Every accuracy figure in this project is measured on documents we made.**
See §6.

---

## 3. How this project works

These are not style preferences. Each was adopted after something went wrong
without it, and several are enforced by tests.

- **Measure before and after, per gate.** A gate is one change with one
  question. No batching two fixes into one measurement — when the number moves
  you must know which change moved it.
- **Stop and report between gates.** Do not chain gates on an assumption that
  the last one worked.
- **Never modify `tests/gold/labels/`.** Gold is never regenerated from engine
  output. If the engine's output shape changes, change
  `tests/harness/adapter.py`. A label set edited to match the engine measures
  nothing.
- **Revert rather than tune.** If a change costs accuracy, take it out. Tuning
  a threshold until the corpus goes green fits the corpus, and the corpus is 10
  documents we wrote.
- **Prove the test fails before the fix.** A test written after a fix, never
  seen red, tests nothing. Several tests in this repo name the commit at which
  they fail.
- **When a fixture passes and reality fails, suspect the fixture.** This has
  happened repeatedly and is the most expensive failure mode here. The gold
  templates came from a tool that materialised an explicit empty cell for every
  slot; the editor never does. The harness read 98.5% while everything a human
  drew by hand scored **zero slots**. Five hand-drawn templates now sit in
  `tests/gold/hand_drawn/` for exactly this reason.
- **No document-specific constants.** No branch on a filename, an issuer name
  or a page count. Thresholds are corpus-measured and their measurement is
  recorded (`SHARD_SHRED = 1.05`, `OVERPRINT_TOP_TOL = 1.0`, the 8-line record
  cap).
- **Say UTF-8 out loud** in every measurement script. `locale.getpreferredencoding()`
  here is cp1252, and it has twice produced a false before/after difference.
- **Check a diagnosis against the code before acting on it.** **Seven round-2
  causes were overturned by measurement**, including all three of I8's. A report
  describes symptoms accurately and attributes them by inference; the
  attribution is what turns out to be wrong. Reproduce first, read the code,
  then fix — and if the cause is not what was claimed, say so in
  `docs/DECISION-LOG.md` and in the report.

`docs/DECISION-LOG.md` is the record of why the engine is the way it is, what
was rejected, and what each decision cost. Read it before changing extraction
behaviour. Three rules were **rejected on measured evidence** and must not be
re-derived: the strict span rule (§2), gate rule G (R6) and the label-witness
gate (§22).

---

## 4. What round 2 closed with

Fourteen defects, `docs/DocAgent_round2_report.md`. Status:

| | defect | outcome |
|---|---|---|
| I1 | region selection ignores template semantics | **fixed** — a band binds one region, a region is a page, and everything left out is flagged |
| I2 | no provenance reaches the output | **fixed** — every value and row carries its quote and file page |
| I3 | band expansion | accepted, never a defect |
| I4 | structurally distinct rows dropped | **fixed** — the gate stays, the silence goes |
| I5 | label boundary and contamination | **fixed** for the text-layer half; one mode measured as a proven zero |
| I6 | value formatting document-dependent | **fixed** — notation derived from the source string at export |
| I7 | text-layer ordering artifacts self-validate | **fixed on one axis** — see §5, the other axis is open |
| I8 | values from the wrong source field | **DISSOLVED** — all three causes overturned (§22) |
| I9 | column assignment unverifiable | **fixed** — `check_placement` reads column bands off the document's own heading line |
| I10 | degraded text layers, small confident wrong answers | **fixed** — a word may not span a font size; shredded pages rebuilt and announced |
| I11 | non-atomic prose as a field value | **fixed (lenient)** — demoted and flagged, never blanked |
| I12 | region emitted twice with no values | **fixed** with I1 |
| I13 | column widths not auto-fitted | **fixed** — `_fit_columns` runs after the writer |
| I14 | template formatting lost on export | **fixed** — the slot writer calls `_apply_cell_style` |

### The one open problem

**A field the document does not answer, filled from something nearby**
(`docs/KNOWN-LIMITATIONS.md` WRONG #3). `Customer Email Address` came back as
the supplier's own `care@engieresources.com`, grounded, at `high`, unflagged.
Pinned as a strict xfail in
`tests/test_round2_I1.py::TestRun9AbsentFieldsStayEmpty::test_the_suppliers_email_is_not_the_customers`.

Every gate the engine has is a property of **the page**; this is a property of
**the claim**, so no geometric check reaches it. A second verification call was
scoped, measured live and **rejected** (§22a, `docs/SECOND-CALL-VERIFICATION.md`).

**The lead worth pulling** is §22a Finding 3, the incoherence result: asked
about `care@engieresources.com` in one response, the model asserted that it
answers `Customer Email Address`, that the label printed beside it is
`Email Us`, and that it belongs to the **ISSUER**. Those cannot all be true,
and unlike every rejected gate it needs no expectation supplied by us — the
contradiction is inside the model's own output. Raw response committed at
**`tests/fixtures/attribution_raw/heldout.json`**.

It is unbuilt because the binding constraint is corpus breadth, not method: ten
documents, nine types, one purchase order. The party signal's only measured
failure — 7 of 27 party-bearing values, all on that one PO, whose parties the
model reverses — cannot be bounded on one instance.

---

## 5. The OCR task

**Why it matters now.** Client documents are **mostly scans**. Cheques are
central to the work. The proportion that is handwritten is **unknown** and is
the first thing to find out, because it decides whether this is an OCR problem
or a handwriting-recognition problem, and those are not the same project.

### The contract OCR has to satisfy

The engine does not read text. It reads **words with positions**, from
`page.extract_words(extra_attrs=["size"])` in `text_layer.read_page`. A word is
a dict:

```python
{"text": str, "x0": float, "x1": float, "top": float, "size": float,
 "page": int,            # stamped by stamp_page, 1-based FILE page
 "overprinted": bool}    # set by mark_overprints
```

Everything correctness-critical is built on that and on nothing else:

- **grounding** — `verify_span` checks the model's quote against text the
  engine read independently, and `printed_numbers` requires a number to equal a
  whole printed number
- **positional evidence** — `column_bands` / `check_placement` (is this value
  under the column it claims), `repair_wrapped` (a figure wrapped inside a
  narrow box), `canonical_value` and `gutter_for_page` (one join rule for a
  multi-line value), `overprinted_spans` (two texts printed over each other)
- **row identity** — `source_occurrences` and `line_page`, which is what makes
  a row identified by *which line* it was read from rather than by what the
  line says

**A scan has none of it.** Today a page with no text layer produces no words,
so every one of those checks silently has nothing to work with.

### The design intent

**OCR is another reader behind the same word-list contract.** It returns the
same dicts with the same keys and the same coordinate space, and
`read_page` chooses the reader. Nothing downstream learns that OCR happened.
If that holds, grounding, positional evidence and row identity keep working
unchanged, and the ~2,500 lines of geometry already written keep their value.

If it does not hold — if OCR words cannot carry trustworthy `x0`/`top`/`size` —
that is the finding that reshapes the project, and it should be established
before anything is built on top.

**Read first, extract second. Never one call that both reads and answers.**
A vision model asked to read a scan *and* fill the template in one call
produces a value with no independently-read text to verify it against, which
collapses grounding into self-report. That is precisely the failure the whole
confidence vocabulary exists to prevent: `UNVERIFIED` means "no text layer
existed to check any span against", and it is not a middling measurement, it is
no measurement. An OCR pass produces the text layer; extraction then runs
against it exactly as it does for a digital PDF.

**MICR is its own reader, with checksum validation.** `engine/micr.py` already
parses the E-13B band — both the real glyphs `⑆ ⑇ ⑈ ⑉` and the ASCII stand-ins
different font vendors emit — and checks the routing number against the **ABA
check digit** before reporting it. Nine digits in the transit position that
fail the checksum are not reported. On a scanned cheque the band is an image,
and E-13B is a fixed-pitch font designed for machine reading: it deserves a
dedicated reader rather than whatever general OCR returns, and the checksum is
already there to reject a bad read. `CHQ-001847` went 45.5% → 100% when the
band was parsed instead of prompted.

---

## 6. Known but unbuilt

- **The image path exists and bypasses the slot pipeline.** `_is_image_file`
  (jpg/jpeg/png/webp/tiff/tif/bmp/heic/heif/gif/avif) routes to
  `_extract_image_with_template`, which uses the older `_build_vision_prompt` →
  `_process_vision_result` path with `prompt_registry.py`. It marks every value
  `unverified`, always sets `needs_review=True`, and is **the one surviving
  second path**. It is honest about what it does not know, and it is not a
  foundation to build OCR on — it is the thing OCR replaces.
- **Scanned PDFs are not detected.** `_is_text_pdf(path, min_chars=80)` is
  defined in `extract.py` and **called from nowhere**. Confirmed by grep across
  the repo. A scanned PDF currently goes down the digital path and produces
  almost nothing.
- **The shredded-text-layer warning does not detect scans.** It fires on a good
  text layer read badly (shard ratio ≥ 1.05) and is silent on a thin OCR layer:
  `round2/bank-statement-sample.pdf` is 108 words over 66 images and scores
  1.00. Two failures, two signals — DECISION-LOG §21.
- **No token accounting per job.** `extraction_jobs` has `total_tokens` and
  `total_cost` columns; the Analytics page hardcodes a rate. Nothing measures
  actual spend per document. OCR changes the cost shape, so this is worth
  having before rather than after.
- **No coverage indicator.** Rows emitted vs candidate rows detected was
  prototyped and **rejected on evidence**: on a corpus scoring 97.2% it read
  0.15–0.75, median 0.38, which trains people to ignore it. The candidate
  counter over-counts lines rather than rows; that is where a next attempt
  starts (§21). Silent under-extraction on degraded input is exactly the OCR
  failure mode, so this becomes relevant again.
- **Line clustering is blind to layer — I7's remaining axis.** `group_lines`
  clusters on `y` within `LINE_TOL = 3.0`. I10 fixed word grouping across font
  sizes; line clustering was left untouched. On `HTR-043235` page 3, 52 words
  across four font sizes collapse into one 641-character line, and 52% of that
  page's words are overprint-tagged — which trips the document gate and
  condemns correct values alongside wrong ones. Recorded in KNOWN-LIMITATIONS.
  OCR output is likely to have *worse* line structure than a digital text
  layer, so this will get louder.

---

## 7. The constraint that matters

**There are no client documents in this repo.**

Everything above is measured on 69 PDFs, 61 of which we drew ourselves, plus
eight real-world files of which four carry the evidence. The gold corpus is ten
in-house documents averaging about 248 tokens of text. Not one client document
has been seen.

So:

- Every accuracy number is a measurement of documents we wrote, and §22's
  finding is the sharp form of it — the gold corpus contains **no defective
  field slot at all** (110 correct, 5 near, nothing wrong, missed or
  hallucinated). It can price a check's false positives and cannot price its
  true ones.
- The shapes a real user draws, and the documents a real client sends, are the
  ones not in that sample. This is already written down about `_gate_findings`:
  23 templates is evidence, not proof, and every one of them was drawn by us.
- **First contact with real client documents will be live.** There is no
  staging corpus to fail against first.

The practical consequence for the OCR work: get a sample of real client
documents — including the cheques, and enough of them to know the handwriting
proportion — **before** choosing an OCR engine or writing a reader. The
questions that decide the design (does OCR carry usable coordinates, is the
MICR band legible at the scan resolution used, what fraction is handwritten)
are all answered by documents, and none of them can be answered from this
repo.
