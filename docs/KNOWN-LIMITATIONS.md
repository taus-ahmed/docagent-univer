# DocAgent — Known Limitations

What this system does **not** do yet, with the condition that triggers each one.

This file exists so the limits can be stated plainly rather than discovered by
someone relying on them. An entry here is a limitation we know about and can
describe; anything not here is either working or not yet looked at, and the
"Not yet exercised" table at the end says which.

Every entry gives the **trigger condition** — the structural property of a
document or template that brings the fault out — not the specific document that
happened to expose it.

Last reviewed: 2026-09-04. Measured against `tests/test_pdfs/` (60 documents)
and the 10 gold-labelled documents in `tests/gold/labels/`.

---

## Numbers and notation

### European decimal comma is read as a thousands separator

**Trigger.** Any document using `,` as the decimal separator and `.` as the
thousands separator — the convention across most of continental Europe.

**Behaviour.** `coerce_cell_value` strips commas before parsing, so `€45,00`
(forty-five euros) becomes `4500.0`. The value is wrong by a factor of 100 and
nothing flags it: `4500.0` is a perfectly plausible number, and the source
string `€45,00` really is printed on the page, so grounding passes.

**Scope.** Affects the exported cell and the stored numeric value. The verbatim
string in `extraction_json` is still correct.

**Why not fixed.** Deciding a document's numeric convention needs evidence
across the whole document — a single value is ambiguous (`1,234` is valid in
both). Guessing per cell would corrupt US documents to fix European ones.

**Related, same cause and equally untested:** multi-currency documents, values
carrying a trailing `CR`/`DR` indicator, and non-Latin digit shapes.

---

## Records that span several printed lines

### A row's cells are only verified against the ONE line the model quoted

**Trigger.** A document where one logical record occupies more than one printed
line — a form laid out in boxes, a table whose rows wrap.

**Behaviour.** Grounding requires each cell's value to sit inside the row's own
quoted source span. When the model quotes only the first line of a multi-line
record, the values printed on its other lines are correctly reported as
ungrounded and demoted to `low`, even though they are right.

**Observed.** `FORM-W2-2023.pdf` returns all twelve figures correctly and marks
all three rows `low`, because the quoted span covers the Box 1/Box 2 line and
not the Box 5/Box 6 line beneath it.

**This is the safe direction.** Nothing wrong is reported as confident. The cost
is noise, not error.

**Why not fixed here.** The fix is to let a record's span cover the lines it
actually occupies, which is the same problem as telling one record from the next
— see *Document boundaries* below. Loosening grounding to "the value appears
somewhere in the document" would remove the check that catches fabricated rows.

---

## Document boundaries

### One file is one document, unconditionally

**Trigger.** A single PDF containing more than one instance of a document —
twenty invoices, a statement run, a batch of cheques.

**Behaviour.** No boundary detection exists anywhere in the pipeline.
`preprocess_file` returns one `ProcessedDocument`; `compute_shape` enumerates
one set of slots for the whole file; `build_prompt` embeds every page in one
prompt and never mentions documents at all. Measured on three invoices merged
into one PDF: **13 field slots where 3 × 13 were needed**, one slot addressed
"Invoice Number" against three distinct invoice numbers in the text. The model
returns one. **The other two invoices are lost with no error, no flag and no
note.** Line items from all three flow into a single band, flattened together.

`FORM-W2-2023.pdf` is already this shape in the corpus — three employees, one
file — and it works only because a template was drawn to treat the three
employees as three rows of one table.

**Status.** Being fixed. This is the top item on the current work list.

---

## Selection markers

### A ticked box and an unticked box read the same

**Trigger.** Any field offering a set of options with one marked as selected —
filing status, entity type, coverage tier, loan class.

**Behaviour.** Untested, and expected to fail. The selection marker is not
resolved, so both the selected and unselected option text can be returned as
fact, and the unselected text grounds successfully because it is printed on the
page.

**Scope.** No document in the corpus contains a selection marker — zero markers
across all four tax forms — so there is currently no fixture and no measurement.

---

## Templates

### The save gate cannot warn about a pure-table template

**Trigger.** A template that is only a declared table — column headings and
blank rows, no label/value fields.

**Behaviour.** `coverage` measures labels that should have slots. A pure-table
template has no such labels, so it reports `labels: 0, complete: True` and the
editor's save gate has nothing to warn on, however wrong the table is.

**Note.** A band of three or more columns also assigns no column the `label`
role — `role` is set to `label` only at exactly two columns. That field is
currently written and read nowhere, so it is not itself a defect.

### Declared table regions are absolute coordinates

**Trigger.** Inserting or deleting a row or column in a template that declares a
table region.

**Behaviour.** The editor cannot insert or delete rows today, so this cannot
happen yet. If insertion is added without shifting declarations in the same
commit, a declaration will point confidently at the wrong cells — worse than no
declaration at all. The required arithmetic is in the box comment in
`template_shape.py`.

---

## Not yet exercised

No fixture exists for any of these, so nothing is claimed about them either way.

| Condition | Status |
|---|---|
| Scans and image-only PDFs | Unsupported — no OCR. Values are marked `unverified`, never confident |
| Tables spanning a page break | Untested |
| Negative values in parentheses | Handled in export (`(1,234.50)` → `-1234.5`, accounting format preserved); untested end to end |
| Non-US decimal and thousands separators | **Known wrong** — see above |
| Multi-currency documents | Untested |
| Rotated or landscape pages | Untested |
| Colour or shading carrying meaning | Untested — no colour is read |
| Footnote markers attached to values | Untested |
| Values split across merged cells | Untested |
| Right-to-left or non-Latin scripts | Untested |

---

## Fixed, recorded here because the failure was invisible

Kept so that a reader who saw the old behaviour knows it changed.

- **Values the PDF wrapped inside a narrow cell** (`$1,268.7` on one line, `5`
  on the next) were handed to the model truncated. Both halves ground, so wrong
  values were reported `high`. On `FORM-W2-2023.pdf`: 11 of 12 figures wrong,
  every one confident, and the single correct figure the only one marked `low`.
  Fixed by reassembling on shared right edge — `engine/text_layer.py`.
- **A value written into the wrong column** passed every check, because a
  flattened text line carries no columns. A Debit reported as a Credit quoted
  the same source line and was marked `high`. Now checked against column bands
  read off the document's own heading line.
- **Currency symbols and trailing cents were lost on export.** The stored value
  was always correct; only the spreadsheet cell dropped the notation. Now
  carried as an Excel number format, so the cell still sums.
