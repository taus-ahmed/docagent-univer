# DocAgent — Known Limitations

What this system does **not** do yet, with the condition that triggers each one.

This file exists so the limits can be stated plainly rather than discovered by
someone relying on them. Every entry gives the **trigger condition** — the
structural property of a document or template that brings the fault out — not
the specific document that happened to expose it.

Part 1 is what is still wrong. Part 2 is what has never been tried, so nothing
is claimed about it either way. Part 3 is what has been fixed, kept because each
of those failures was invisible in the output, and a reader who saw the old
behaviour deserves to know it changed.

Last reviewed: 2026-09-04, against `tests/test_pdfs/` (60 documents), the 10
gold-labelled documents in `tests/gold/labels/`, and the 7 scenario fixtures in
`tests/fixtures/scenarios/`.

---

# Part 1 — Still wrong

## A tick that is neither printed nor a form widget cannot be recovered

**Trigger.** A flattened or scanned form where the tick is vector graphics or
pixels — present in neither the text layer nor an AcroForm widget.

**Behaviour.** Every option is printed on the page and grounds perfectly, so any
answer passes every check the pipeline has. A prompt rule ("a line offering
several options and marking none has no answer") takes a fixture of four such
fields from 1 correct to 3, and costs nothing elsewhere — the gold harness is
unchanged and no-template improved. **A prompt rule is a request, not a
guarantee**: one field still answers `Accrual` out of `Accrual Cash`, at `high`.

**Blast radius.** Categorical fields decide treatment — filing status, entity
type, coverage tier, loan class. A wrong one is not a formatting problem.

**The deterministic fix** is to look for ticks in the page's vector graphics
(`page.curves` / `page.rects` inside a checkbox rectangle). Separate work.

**Fixture.** `tests/fixtures/scenarios/selection_no_marker_in_text.json`, with
an expected-to-fail test.

---

## European decimal comma is read as a thousands separator

**Trigger.** Any document using `,` as the decimal separator and `.` as the
thousands separator — the convention across most of continental Europe.

**Behaviour.** `coerce_cell_value` strips commas before parsing, so `€45,00`
(forty-five euros) becomes `4500.0`. Wrong by a factor of 100, and nothing flags
it: `4500.0` is plausible, and `€45,00` really is printed on the page, so
grounding passes.

**Scope.** The exported cell and the stored numeric value. The verbatim string
in `extraction_json` is still correct.

**Why not fixed.** Deciding a document's numeric convention needs evidence
across the whole document — a single value is ambiguous (`1,234` is valid in
both). Guessing per cell would corrupt US documents to fix European ones.

**Same cause, equally untested:** multi-currency documents, values carrying a
trailing `CR`/`DR`, non-Latin digit shapes.

---

## A running header on every page would split a long report wrongly

**Trigger.** A multi-page document printing the SAME first line on every page.

**Behaviour.** Each page would be read as a separate document, producing N
stacked blocks most of which are mostly empty.

**Why it is accepted.** The costs are not symmetric. Splitting wrongly is ugly,
obvious and fixed in one look; NOT splitting silently discards every document
but one, which is what this replaced. No document in the 60-document corpus has
a running header — all 17 multi-page ones have a different first line on page 2
— and the detector has **0 false positives across the whole corpus**.

**If it happens**, the run logs `N documents in one file` and every result
carries `document_index` and `source_pages`, so the cause is visible rather than
mysterious.

---

## Cost scales with documents per file

**Trigger.** A large merged upload.

**Behaviour.** Splitting a file into N documents makes N extraction calls, not
one. That is honest — twenty invoices is twenty documents of work — but someone
uploading a 200-page merged file is buying 200 calls, and nothing warns them
first.

---

## Without geometry, row identity is weaker

**Trigger.** The image path, or any caller that passes no `page_lines`.

**Behaviour.** A row is identified by its source span PLUS its own values rather
than by which document line it came from. Two genuinely different rows quoting
one line both survive, which is the important case — but a **hallucinated
variant** of a real row (same source line, one value altered) also survives,
where the positional rule would catch it.

**Fix.** Thread `page_lines` through `_extract_image_with_template`. An image
has no text layer to take word positions from, so this needs positions from the
vision step, or an explicit statement that the image path cannot make this
check.

---

## The save gate's pure-table rules are calibrated on 23 templates we drew

**Trigger.** A template shape none of the repo's 23 templates resembles.

**Behaviour.** Three rules fire on a pure-table template — a band column with no
heading (warn), a band with no headings at all (block), two declared regions
overlapping (warn). All three fire on **0 of 23** real templates and on four
deliberately broken ones. But that sample was drawn by us, and the shapes a real
user draws are exactly the ones not in it.

**Mitigation.** Only the unambiguous rule blocks; the others warn and let the
save through. A fourth candidate — duplicate headings inside one band — was
rejected for firing on `bs_luq`, a real production template doing a legitimate
thing.

**If a legitimate template is blocked**, the rule is likelier wrong than the
template: `tests/test_save_gate.py::TestNoRealTemplateTripsTheGate` runs every
template in the repo and is where to add it.

---

## Declared table regions are absolute coordinates

**Trigger.** Inserting or deleting a row or column in a template that declares a
table region.

**Behaviour.** The editor cannot insert or delete rows today, so this cannot
happen yet. If insertion is added without shifting declarations in the same
commit, a declaration will point confidently at the wrong cells — worse than no
declaration at all. The required arithmetic is in the box comment in
`template_shape.py`.

---

# Part 2 — Not yet exercised

No fixture exists for any of these, so nothing is claimed about them either way.

| Condition | Status |
|---|---|
| Scans and image-only PDFs | Unsupported — no OCR. Values are marked `unverified`, never confident |
| Tables spanning a page break | Untested |
| Non-US decimal and thousands separators | **Known wrong** — see Part 1 |
| Multi-currency documents | Untested |
| Rotated or landscape pages | Untested |
| Colour or shading carrying meaning | Untested — no colour is read |
| Footnote markers attached to values | Untested |
| Values split across merged cells | Untested |
| Right-to-left or non-Latin scripts | Untested |
| Negative values in parentheses | Handled at export (`(1,234.50)` → `-1234.5`, accounting format kept); untested end to end |

---

# Part 3 — Fixed

Each of these failed *invisibly*: the output looked right.

## Several documents in one file were read as one

Three invoices merged into one PDF gave **13 field slots where 3 × 13 were
needed** — one slot addressed "Invoice Number" against three distinct invoice
numbers. The model answered for one; the other two were lost with no error, no
flag and no note.

`engine/doc_boundaries.py` splits the file and runs the pipeline once per
document; each result carries `document_index`, `document_count` and
`source_pages`. Two deterministic signals, no model call: a repeated title
within a run of same-type pages, and a change of document type. **0 false
positives across all 60 corpus documents; 14 of 14 merged files split at exactly
the right pages**, including twenty invoices, five two-page payslips, and mixed
batches with runs of one type inside them.

## Values the PDF wrapped inside a narrow cell

`$1,268.7` on one line and `5` on the next — the split is in the file, not the
reader, so both halves ground. On `FORM-W2-2023.pdf`: **11 of 12 figures wrong,
every one `high`, and the single correct figure the only one marked `low`.** Now
12 of 12, reassembled on shared right edge (`engine/text_layer.py`).

## A value written into the wrong column

A flattened text line carries no columns, so a Debit reported as a Credit quoted
the same source line and was marked `high`. Now checked against column bands
read off the document's own heading line; a misplaced value is demoted and
flagged with the column it actually sits under, and kept rather than deleted.

## A record spanning several printed lines came back low

Cells were verified against the ONE line the model quoted, which is right for a
table and wrong for a form. `record_span` runs from a row's line to the next
row's line, so a cell is checked against its own record and **cannot reach into
a neighbouring one**. Grounding was *not* loosened to "appears somewhere in the
document" — that would have removed the check that catches fabricated rows.

## A selection state stored as a form widget was invented

A real fillable form's checkbox is a widget annotation carrying no text, so the
text layer showed every option and no marker. Four option fields, all four
filled from thin air at `high` with `needs_review=False`, answering `Services`
where the form says `Wholesale trade`. `acroform_widgets` now reads `/AS`
(falling back to `/V`) off every `/FT /Btn` widget and writes `[X]` / `[ ]` into
the text at the widget's own x. 8/8, and not one unselected option reported.

Fixture: `tests/fixtures/FORM-CT3-FILLABLE.pdf`, built by
`tests/fixtures/make_fillable_form.py` — committed as a script as well as a PDF
so it can be read and argued with. Zero of the 60 corpus PDFs carry AcroForm
fields, which is why this had never been testable.

*(With markers printed in the text, `[X]` / `[ ]`, it was always correct — 9 of
9, not one unselected option reported. The defect as originally written does not
reproduce in that form.)*

## Rows were deleted for quoting the same line as an earlier row

Identity was the source span's TEXT, so a group header, a repeated column
heading or any line a document prints twice cost every row after the first —
silently, reported only in a validation note nothing reads. Worst in exactly the
case the product is for: five merged invoices made 33 rows deletable, five
payslips 43, scaling linearly with documents per file. Identity is now the
document LINE a row was read from, and anything still dropped is flagged with
its content and marks the document for review.

## Currency symbols and trailing cents were lost on export

The stored value was always correct; only the spreadsheet cell dropped the
notation. Now carried as an Excel number format, so the cell still sums.

## The save gate could not warn about a pure-table template

`coverage` measures labels that should have slots. A pure-table template has
none, so it reported `labels: 0, complete: True` and the gate had nothing to say
however wrong the table was — as did four deliberately broken templates. Now
covered by `coverage["warnings"]` and `coverage["blocking"]`; see Part 1 for
what remains uncertain about the calibration.
