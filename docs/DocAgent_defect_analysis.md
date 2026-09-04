# DocAgent — Defect Analysis

Behavioural defects observed across seven extraction runs. Written document-agnostically: each entry states the **structural condition** that triggers the fault, not the specific values that failed. The test documents were chosen as representatives of common real-world layouts; fixes should target the condition, not the document.

---

## Test inventory

| ID | Template shape | Table declared? | Doc |
|---|---|---|---|
| T1 | Key-value list, one value column, 11 fields | n/a | H25B |
| T2 | 3-column table, headings across a row | No | H24B |
| T3 | 2-value-column matrix, headings across a row | No | H25B |
| T4 | Three side-by-side key-value blocks | n/a | H25B |
| T5 | 5-column table, 39 rows, **empty top-left cell** | Table down | H25B |
| T6 | 5-column table, 39 rows, **labelled top-left cell** | Table down | H25B |
| T7 | Repeat of T6, unchanged | Table down | H25B |

T6 and T7 are byte-identical across the main band. Core extraction on a declared band is **deterministic**. Instability is confined to two defects (D5, D9).

---

## Severity 1 — data loss and silent corruption

### D1. Grouped tables lose the value column that the group headers also occupy

**Trigger condition.** A table whose rows are organised into groups, where each group-header row carries its own value in the *same* column the line items use.

**Behaviour.** Line-item values in that column are captured for the first group and dropped for every group thereafter. The label extracts correctly; only the value is absent. No error, no flag, no distinction between "empty in source" and "failed to extract."

**Why this matters beyond the test doc.** This is the default shape of almost every financial document: invoices with grouped line items, P&L statements with category subtotals, trial balances, expense reports, bank statements grouped by transaction type. A grouped table where amounts share one column is the norm, not an edge case.

**Hypotheses.**
- *H1 — group-total binding.* Values are bound to the group-header row, which is then discarded (see D2), taking the values with it.
- *H2 — row-index drift.* Values are keyed by row index; skipping header rows without reindexing causes assignments to drift onto rows that no longer exist and be dropped. Fits the observed pattern of first-group-survives, all-later-groups-fail.
- *H3 — column claimed.* The column is classified as a "totals" column because group headers put totals there, and per-row values are suppressed as conflicting.

**Diagnostic.** Pull the raw results payload for any row in the second group. Four outcomes, four different fix locations:
- Value present with a column key → writer-side loss
- Value present bound to a header row → H1
- Value absent entirely → prompt or region map, not the writer
- Value present with LOW confidence → a suppression filter is discarding it

Single highest-value lookup available. Do this before any code change.

---

### D2. Rows that don't match the dominant row pattern are discarded

**Trigger condition.** A declared table band containing rows of more than one structural type — line items plus group headers, subtotals, totals, or credit/adjustment lines.

**Behaviour.** Only rows matching the dominant pattern are emitted. Group headers, subtotal rows and grand-total rows are dropped entirely — label and value both.

**Consequence.** Output has no group structure. A reviewer cannot tell where one group ends and the next begins, and cannot check any figure against its subtotal. For accounting review this is disqualifying regardless of how accurate the surviving line items are.

**Note this is a regression, not a missing capability.** In T5 (empty top-left cell), group totals and the full multi-column subtotal row *were* captured, correctly placed across all five value columns. In T6/T7 they are gone. The two behaviours appear mutually exclusive: the classifier switches between "rows are numeric records" and "rows are labelled line items," and neither mode emits both. The five-column placement logic works — it is being bypassed, not missing.

---

### D3. Rows carrying values in multiple value columns lose all but one

**Trigger condition.** A single row with amounts in two or more value columns.

**Behaviour.** One value survives. Observed on a line item split across two columns; the second was silently dropped. One value column was never populated in any of the three 5-column runs.

**Competing generalisation, unresolved.** T5 placed a subtotal row across all five columns correctly, which contradicts a blanket "one value per row" cap. Two readings remain:
- (a) rows that carry a *label* plus multiple values lose all but one, while unlabelled rows do not
- (b) one specific column is being misresolved and never receives a value

**Diagnostic.** Inspect the results payload for the multi-value row: one entry or two? Settles it immediately.

**Real-world blast radius.** Comparative statements (current year / prior year), debit-credit ledgers, allocations split across parties or cost centres, tax forms with federal/state columns. Any document where one line legitimately carries more than one amount.

---

### D4. Label/value boundary misplaced when a numeric label prefix abuts a numeric value

**Trigger condition.** A label ending in digits (line number, item code, GL code, field identifier) immediately followed by a value beginning with digits, with no intervening non-numeric character.

**Behaviour.** The boundary is placed inside the value. The label absorbs the value's leading digits, producing a syntactically valid but numerically different figure.

**Why this ranks above the other data-loss defects.** Every other defect on this list produces something a reviewer can *see* is wrong — a blank cell, a missing row, a misplaced figure. This one produces a plausible wrong number. On a rate, a percentage or an identifier, it is undetectable without going back to the source.

**Recurrence.** Same defect family as the `EIN: 47-38` case from the first production run, which was a label absorbing part of a tax identifier. Two independent sightings, two different documents, same mechanism.

**Real-world blast radius.** Numbered invoice lines, GL and cost codes, account numbers, tax IDs, percentage rates, item SKUs.

---

### D5. Declared band boundaries are not enforced against page or table boundaries

**Trigger condition.** A document containing more than one table of similar visual structure, where the target band is declared over one of them.

**Behaviour.** Rows from the other table(s) are appended to the band. Four distinct faults compound:

1. **Cross-page leakage.** Content from a different page enters a band declared over one page.
2. **Column misassignment across incompatible schemas.** Appended rows are placed into columns that do not exist in their source table.
3. **Independent records flattened into apparent duplicates.** Two separate tables that legitimately contain the same figure — for example a borrower-side and a seller-side summary — are merged, producing rows that read as duplicated data when they are two valid distinct entries.
4. **Blank template lines emitted as rows.** Unfilled placeholder lines in the source produce label-only output rows.

**This is one of only two non-deterministic areas.** Row count and content of the appended tail differed between two otherwise identical runs.

**Real-world blast radius.** This is the highest-stakes defect for the stated product direction. A multi-document PDF — 100 cheques, 50 invoices, a statement run — is *entirely* composed of structurally similar repeated tables. If band boundaries don't hold against a second similar table on another page, they will not hold against ninety-nine of them.

---

### D6. Column misassignment is invisible to the grounding layer

**Trigger condition.** Any table with more than one value column.

**Behaviour.** A value placed in the wrong column validates as HIGH confidence, because the validator checks whether the value string appears in the extracted text — and the flattened text layer carries no column information.

**Observed across three separate runs** on undeclared and declared tables alike, including one case where the same value landed in different columns on different runs and both were marked HIGH.

**Why this is the architectural finding of the week.** The product's central claim is that every extracted value is grounded in quoted source text and verified. That guarantee holds for *value existence*. It does not hold for *value placement*. In a multi-column financial table, placement is most of the meaning — which column an amount sits in determines who owes it. The verification layer is structurally blind to the failure mode most likely to occur in the documents the product targets.

This is not fixable by tuning the prompt. It needs positional evidence — bounding boxes, column index, or a cell-level anchor — carried through validation alongside the text match.

---

### D7. Selection-state markers are not resolved; unselected options are emitted as fact

**Trigger condition.** Any field presenting a set of options with one marked as selected.

**Behaviour.** Output returns the raw marker together with the selected option *and* unselected options. The result asserts something the document explicitly negates.

**Compounding factor.** The unselected option's text does appear in the document, so the grounding check confirms it and marks it HIGH confidence. Another member of the D6 family: a value the source contradicts, passing verification.

**Real-world blast radius.** Tax forms, loan applications, compliance and eligibility forms, insurance declarations, onboarding paperwork. Selection fields typically carry categorical distinctions that determine treatment — filing status, entity type, loan class, coverage tier. Getting one wrong is not a formatting problem.

---

## Severity 2 — integrity and consistency

### D8. Numeric normalisation loses formatting and breaks the grounding chain

**Trigger condition.** Any value containing a currency symbol, thousands separator, or trailing zero.

**Behaviour.** The value is normalised and written to Excel as a number. Currency symbol, separators and trailing cents digits are lost.

**Two distinct problems.**

1. **Presentation.** Financial output that drops the currency symbol and the second decimal will not pass accounting review, regardless of numeric accuracy.
2. **Grounding integrity.** The stored value no longer matches the string the validator grounded it against — the normalised form does not literally appear in the document. Either the comparison is normalising too (which weakens the guarantee, since a normalised match will accept values the document doesn't contain) or these cells should be returning LOW confidence and aren't.

**Diagnostic.** Compare the stored value, the stored source quote, and the confidence flag on any coerced cell. If value and quote have diverged while confidence reads HIGH, that needs an explicit product decision: store the display string, store both, or document the normalisation as intended behaviour.

**Untested and probably worse.** Negative amounts in parentheses, non-US decimal and thousands separators, multi-currency documents, values with trailing credit/debit indicators. None of these appeared in the test set. All are routine in real accounting documents.

**Related.** Value typing is inconsistent *within a single column* — some cells written as numbers, some as text, depending on whether a stray character survived. Identifier fields are correctly stored as text (preserving leading zeros) but this raises Excel's "number stored as text" warning triangle, which reads as an error to a reviewer.

---

### D9. Multi-line value assembly has no fixed rule

**Trigger condition.** Any field whose value wraps across lines in the source.

**Behaviour.** Three different outcomes observed, with no discernible rule:
- joined with the space preserved
- joined with the space dropped, fusing two words
- truncated at the first line, later lines discarded

**Non-deterministic.** The same field in the same document produced different joins on different runs. Also inconsistent *within* a single run — adjacent fields of the same type treated differently.

**Real-world blast radius.** Addresses, payee and remitter names, item descriptions, memo and reference lines, terms text. Wrapped values are unavoidable in any document with a fixed-width layout.

Note: whether a name field *should* absorb its address is a legitimate design question. That it varies between adjacent fields, and between runs, is not.

---

### D10. Multi-cell header bands are emitted twice

**Trigger condition.** A header band spanning several columns.

**Behaviour.** The band is written once collapsed into a single cell, then again correctly split across its columns on the following row. Both versions persist in output.

Carried forward from the first production run; not re-triggered by the test templates, which used single-row headings.

---

### D11. Sub-headers that change a column's meaning are dropped

**Trigger condition.** A table interrupted mid-way by a sub-header that redefines what a column contains.

**Behaviour.** The sub-header is not emitted. The column silently holds values answering two different questions, with no marker at the boundary.

**Real-world blast radius.** Statements that switch from deposits to withdrawals mid-table, forms that shift from one question set to another under a shared answer column, schedules with mid-table category changes.

---

## Severity 3 — template editor

These are not extraction faults. They are faults in how a user's intent gets captured — and each fails silently, producing a template that is wrong before extraction begins.

### D12. Slot marking is purely positional with no semantic awareness

The rule — *text cell = label, adjacent empty cell = slot* — cannot distinguish a field label from a column heading from a section title. Three consequences, all silent:

**(a) An empty top-left cell disables an entire column.** With no text cell to anchor against, no slots are created down that column, and the whole column returns blank. Typing any label into the corner cell resolves it completely. A user has no way to know this from the UI.

**(b) Section titles receive spurious slots.** Slots are created beside region headings, inflating the slot count. The engine correctly leaves them blank, so no bad data results — but on a template with many section headings the user must notice and clear each one manually.

**(c) Multi-column regions cannot be expressed without an explicit Table declaration.** Undeclared multi-column regions are classified as single-value key-value regions. Two failure shapes observed: values shift left into the first value column (when a leading value cell is empty), or the second and subsequent value columns are never populated at all.

**The workaround works.** Explicitly declaring a table produced correct multi-column placement. So the capability exists; the free-form rule simply doesn't reach it. The product decision is whether to extend the rule or require declaration — but either way the current silent failure needs a warning: a declared band with a zero-slot column, or an undeclared multi-column region, should surface something in the UI.

### D13. Template formatting is not preserved on export

Merged cells, centring and cell borders present in the editor are absent from the exported file. What the user builds visually is not what they receive.

### D14. Column width auto-fit applies inconsistently

Applied on some runs, not on others, within the same session. Affects user-supplied label text as well as extracted values, so labels the user typed come back truncated on screen.

---

## Behaviour that is correct — protect under regression

A fix for D1/D2 will touch row classification, which is exactly the logic producing these results. Each should have a regression test before that work starts.

| Behaviour | How it was demonstrated |
|---|---|
| **No invention for absent fields.** A template field that does not exist in the target document returns empty rather than being filled from a plausible neighbour | A field belonging to a different form variant returned empty despite several tempting near-matches on the page |
| **No unrequested content forced into a grid.** Content adjacent to the target region is not pulled in to fill available rows | A neighbouring row present in the source was correctly omitted from a template that didn't ask for it |
| **Multi-column placement, when the band is declared.** All five value columns populated in correct order on a multi-value row | T5 subtotal row |
| **Side-by-side key-value regions.** Multiple independent label/value blocks across one sheet, no cross-contamination between blocks | T4, all fields placed correctly |
| **Leading zeros preserved on identifier fields** | Identifier stored as text rather than coerced to number |
| **Semantic label matching across form variants.** A template label that differs in wording from the document's label still matches | Template and document used different terms for the same field |
| **Label extraction quality.** Line numbers, payee text and inline detail all extracted intact | T6/T7, all line-item labels correct |
| **Helper text excluded from labels.** Explanatory sub-text under a field label does not contaminate the label cell | T2 |
| **Blank spacer rows and section headings preserved in output** | T4 |

**Caution on the first entry.** The no-invention result and the semantic-matching result come from the same mechanism pointing in opposite directions. Flexible matching is what lets one template work across form variants; it is also what would let a field be filled from a *differently labelled* value carrying the same number. That case has not yet been tested. Until it is, "no invention" is demonstrated only for fields with no plausible substitute present.

---

## Conditions not yet exercised

The test set covered clean, digitally-generated, single-language, US-format documents with well-behaved tables. Real inputs will include:

| Condition | Status |
|---|---|
| Scans and image-only PDFs | Known unsupported (no OCR) |
| Tables spanning a page break | Untested |
| Multiple independent documents in one PDF | Untested — and D5 suggests it will fail |
| Negative values in parentheses | Untested |
| Non-US decimal and thousands separators | Untested |
| Multi-currency documents | Untested |
| Rotated or landscape pages | Untested |
| Colour or shading carrying meaning | Untested |
| Footnote markers attached to values | Untested |
| Values split across merged cells | Untested |
| Right-to-left or non-Latin scripts | Untested |

---

## Recommended diagnostic order

Each of these is a lookup, not a code change. Together they locate every Severity 1 defect.

1. **Results payload, any line-item row in the second group of a grouped table.** Is the value present, and under what column key and confidence? Locates D1 in extractor / writer / filter.
2. **Results payload, a row carrying two values.** One entry or two? Resolves the D3 ambiguity.
3. **Cached region map for the declared 5-column template.** Confirm all rows are in the band and all value columns are registered. Requires no re-extraction.
4. **Stored value vs stored source quote vs confidence flag, on any coerced numeric cell.** Determines whether D8 has broken the grounding chain or merely the formatting.
5. **Whether positional data exists anywhere in the pipeline** — bounding boxes or column indices from the PDF parse. Determines whether D6 is fixable within the current architecture or needs a new signal carried through validation.

Item 5 is the one that shapes the roadmap. The rest are bugs; that one is a design question.
