# Template layout rules and audit

## Ten-line summary

1. DocAgent does not ingest an `.xlsx` template; it reads one saved editor-grid object containing cells, widths, merges, and optional declared table regions.
2. Any trimmed non-empty cell value is static text; any usable empty cell is a possible slot, and `extractTarget` no longer changes that decision.
3. Scalar slots are horizontal: a value column must be headed or immediately right of a label column, and the owning label is the nearest label column to its left.
4. A label above a blank, a distant blank, placeholder text, or an empty merged range does not create the intended scalar slot.
5. An inferred row band needs two or more adjacent text headers with no text directly beneath those header columns.
6. Reserved rows run from the header to the next detected header or closing static row; a bottom-edge header with at least three columns is assigned ten rows.
7. Totals have no explicit relationship to a band; they are ordinary scalar fields when geometry happens to leave them outside the band.
8. The slot writer expands overflowing row bands and shifts every lower template row, but it never contracts unused reserved rows or rewrites formulas.
9. Basic grid styles and safe merges are recreated; number formats, validation, hidden axes, Excel Table objects, and secondary sheets are outside the saved grid.
10. In this audit, 19/34 scenarios parse exactly and 16/34 round-trip exactly; all other expectations are executable strict xfails.

## What the production code actually receives

An auditor's workbook is not a production input format. The template endpoint accepts one `grid` with a `cells` dictionary, and template parsing reads one JSON `layout` from the saved template description ([`templates.py:83-104`](../backend/app/api/routes/templates.py#L83), [`template_parsing.py:30-46`](../backend/app/services/template_parsing.py#L30)). The editor's complete saved sheet contract is `cells`, `colWidths`, `merges`, `repeatRows`, and optional `regions`; it has no workbook or worksheet collection ([`DocAgentSpreadsheet.tsx:51-56`](../frontend/components/templates/DocAgentSpreadsheet.tsx#L51)).

The audit fixtures are real `.xlsx` files. Test tooling converts the first worksheet into exactly that editor-grid contract. It deliberately does not invent private grid keys for Excel features the editor cannot save. This boundary is itself an audited result, not an application fix.

## Label and scalar-slot rules

- Cell values are converted to strings, trimmed, and treated as static whenever non-empty. `extractTarget` is counted only for migration diagnostics and never changes the shape ([`template_shape.py:135-174`](../backend/engine/template_shape.py#L135)). Consequently, colons, units, asterisks, parentheses, abbreviations, and non-English text need no vocabulary match; placeholder text and formula text are also static.
- The used rectangle is the bounding box of text, declared regions, and merges. Style-only or merely present empty cells do not extend it; a one-column label list is widened by one implied value column ([`template_shape.py:84-132`](../backend/engine/template_shape.py#L84)). Within that rectangle, an absent cell and an explicit empty cell are equivalent ([`template_shape.py:135-170`](../backend/engine/template_shape.py#L135)).
- Covered merge cells are neither labels nor slots. The top-left anchor is the only meaningful cell ([`template_shape.py:48-81`](../backend/engine/template_shape.py#L48)). A text anchor merged across two or more columns is unconditionally a wide heading ([`template_shape.py:191-207`](../backend/engine/template_shape.py#L191)). The code has no rule that makes an empty merged range a writable scalar slot.
- Scalar inference partitions non-band rows into runs, assigns columns local roles, and recognizes a heading row only when its first non-empty row contains more text columns than every later non-empty row ([`template_shape.py:803-874`](../backend/engine/template_shape.py#L803)). Blank rows inside the dense used rectangle do not end a run; this is why scattered groups can contaminate one another.
- A value column is eligible only when a block heading names it or it is immediately right of a label column ([`template_shape.py:809-876`](../backend/engine/template_shape.py#L809)). A right-edge implied value column is allowed only when the block already proves a label/value pattern inside the box ([`template_shape.py:878-889`](../backend/engine/template_shape.py#L878)).
- For each eligible empty cell, ownership is the nearest label *column* to its left, and that exact row must contain a label in that column. The code does not search below a label, choose a nearest empty cell by distance, or skip across arbitrary separator columns ([`template_shape.py:891-933`](../backend/engine/template_shape.py#L891)).
- Scalar slots intentionally carry an empty `section`. The code states that section context for an ordinary field is not detectable from the dense geometry ([`template_shape.py:913-930`](../backend/engine/template_shape.py#L913)). Duplicate `Name`, `Date`, or `Total` fields therefore remain duplicate prompt descriptions.

## Repeating-band rules

- User-declared regions take priority. A row-oriented declaration includes the header row and must be at least two columns wide with at least one data row; a two-column declaration assigns the first column the label role ([`template_shape.py:266-361`](../backend/engine/template_shape.py#L266)). A column-oriented declaration is the only supported way to express a transposed band; its first column supplies field headings and later columns are records ([`template_shape.py:362-388`](../backend/engine/template_shape.py#L362)).
- Without a declaration, a header candidate has at least two text cells, those cells are adjacent, and none of those header columns contains text on the next row ([`template_shape.py:641-653`](../backend/engine/template_shape.py#L641)). A gap between two side-by-side header blocks invalidates the entire row; borders and Excel Table metadata are not consulted.
- The provisional end is immediately before the next header candidate, or the last row in the text-defined range. A later static row closes the band when it fills at least half the band's columns or when no blank row follows it before the provisional end ([`template_shape.py:658-705`](../backend/engine/template_shape.py#L658)). An isolated subtotal with fewer than half the columns populated stays inside a wide band.
- If the calculated band has no body rows, a bottom-edge header with three or more columns gets ten synthetic rows. A two-column bottom-edge header is rejected as ambiguous ([`template_shape.py:706-725`](../backend/engine/template_shape.py#L706)). The code does not distinguish a header-only flat-list template from a header that intended ten reserved rows.
- The band name is the detected section title, otherwise the first header of a two-column label/value band, otherwise `table` or `table_N` ([`template_shape.py:726-747`](../backend/engine/template_shape.py#L726)). Duplicate header keys are disambiguated with their Excel column letter, and only a two-column band gets a label-role first column ([`template_shape.py:748-768`](../backend/engine/template_shape.py#L748)).
- A section is either the nearest prior nonblank wide merged heading or the one lone static cell directly above the header; an unmerged title separated by a blank row is not a section ([`template_shape.py:210-263`](../backend/engine/template_shape.py#L210)).

## Totals, formulas, and native workbook features

- A band map contains name, header row, start/end rows, and columns—no total pointer ([`slot_extractor.py:196-205`](../backend/engine/slot_extractor.py#L196)). A `Total` label becomes an ordinary field only if band-end inference leaves it outside the band and scalar geometry supplies a slot. No code decides whether a total belongs to the table above, below, beside, or elsewhere.
- The prompt describes scalar slots only by row label and optional section; it omits the cell reference and column heading. Tables are described by band name, optional section, exact keys, and claimed blank-row capacity ([`slot_extractor.py:250-287`](../backend/engine/slot_extractor.py#L250)). Thus two sectionless `Name` slots are indistinguishable to a reader, and a wrongly chosen cell is invisible in prompt prose.
- Borders, fills, fonts, alignment, and wrapping are the only editor style properties ([`DocAgentSpreadsheet.tsx:7-12`](../frontend/components/templates/DocAgentSpreadsheet.tsx#L7)). The writer reapplies those properties inside and outside bands, repeating the first body-row style on overflow rows ([`excel_slot.py:377-435`](../backend/app/services/excel_slot.py#L377), [`excel_cells.py:704-730`](../backend/app/services/excel_cells.py#L704)). Shape detection deliberately ignores all styling ([`template_shape.py:84-93`](../backend/engine/template_shape.py#L84)).
- Template merges are recreated after values are written, but any merge crossing a band row is skipped because its meaning after expansion is undefined ([`excel_cells.py:455-482`](../backend/app/services/excel_cells.py#L455), [`excel_slot.py:527-535`](../backend/app/services/excel_slot.py#L527)).
- Formula strings are static cell values to the shape builder. The writer assigns shifted static values back to cells, so openpyxl preserves a formula string at its moved cell, but no code translates its references or expands its range ([`template_shape.py:142-160`](../backend/engine/template_shape.py#L142), [`excel_slot.py:361-375`](../backend/app/services/excel_slot.py#L361)). Formula ownership and recalculation are not decided.
- The saved cell style has no number format, validation, row/column visibility, or Excel Table object ([`DocAgentSpreadsheet.tsx:7-24`](../frontend/components/templates/DocAgentSpreadsheet.tsx#L7), [`DocAgentSpreadsheet.tsx:51-56`](../frontend/components/templates/DocAgentSpreadsheet.tsx#L51)). The slot writer consumes one worksheet, cells, widths, merges, and styles; it has no restoration path for those omitted features or for another template sheet ([`excel_slot.py:27-34`](../backend/app/services/excel_slot.py#L27), [`excel_slot.py:361-435`](../backend/app/services/excel_slot.py#L361)). Where those features should affect meaning, the code does not decide.
- The writer iterates only declared template columns and reads each answer with `row.get(key, "")`; extra answer keys are ignored and missing template keys remain blank ([`excel_slot.py:461-516`](../backend/app/services/excel_slot.py#L461)).

## Growth and document stacking

For each row-oriented table, overflow is `max(0, extracted_rows - reserved_rows)`. A template row is shifted by the sum of overflows from bands ending above it ([`excel_slot.py:334-346`](../backend/app/services/excel_slot.py#L334)). Static text, scalar fields, table rows, styles, and safe merges all use that calculated row ([`excel_slot.py:361-375`](../backend/app/services/excel_slot.py#L361), [`excel_slot.py:436-535`](../backend/app/services/excel_slot.py#L436)). The code never calls `insert_rows`, never contracts a short/empty band, and never inserts a protective gap between two bands in the slot path. It also sums overflows independently, so it has no side-by-side-band grouping rule.

Transposed bands grow rightward and do not shift rows ([`excel_slot.py:221-231`](../backend/app/services/excel_slot.py#L221), [`excel_slot.py:464-488`](../backend/app/services/excel_slot.py#L464)). Multiple documents repeat the full template block and use exactly three blank rows between blocks (`GAP_BETWEEN_DOCS = 3`).

## Run D changes (DECISION-LOG §27)

The rules above describe the engine before Run D. Run D changed these, each
checked against every committed grid:

- A fully blank row ends a field block (F5); a block's heading row must have contiguous texts.
- A header row's statics split into contiguous runs, each its own band (T6); bands sharing rows grow as one group by the largest change; a band ends only on statics in or left of its own columns.
- A row band claims only its own columns; fields beside it on its rows are fields (T15); a pure label list on the right edge implies its value column.
- A label with no usable right cell takes the empty cell below it; when both exist the right is kept (F2 itself is unchanged: its right cell is usable).
- An empty merge just past a label's merge is its slot (F6).
- Placeholder text (`____`, `[ ]`, `{{ }}`, `xxx`, `enter … here`, `TBD`) is an empty slot and is replaced on write (F11).
- A header with nothing beneath it reserves 10 rows. T2/T13 now agree with `tests/test_prod_templates.py`, which pins the same production shape at `>= 5`; since Run C the writer drops unused reserved rows, so the export is unchanged.
- A cell covered by a one-column merge from above takes that merge's heading (T9).
- A subtotal typed inside a table keeps its place on write; records go around it.
- Writer: bands are written with their actual row count (Run C); a failed record keeps the template geometry (T20).
- `template_warnings` reports formulas read as labels, shared rows, implied-or-below slots, unlabelled merged boxes, header-only tables and merges over tables.

After the Part 1 owner rulings: 29/34 scenarios parse exactly and 27/34
round-trip exactly. Strict-xfail: parse F3, F10, T12, T14, T18; write F3, F9,
F10, F12, T12, T14, T18. Four separate strict tests retain F2's future editor
setting and the T6/T10/T15 declared-table intent. The reasons are written on
each marker in `tests/test_template_layout_audit.py`.

## Part 1 owner rulings (authoritative)

1. **T2 and T13 — reserved rows.** A header with nothing beneath it keeps the
   production rule: ten synthetic rows, satisfying the `>= 5` production
   regression. The audit previously expected zero. It now expects ten because
   the same geometry must have one truth; unused rows are dropped, so the
   exported workbook is identical.
2. **T21 — document gap.** Exactly three blank rows separate document blocks.
   This is the owner specification, the Run C acceptance result, and the
   `GAP_BETWEEN_DOCS` constant. The audit's former `+ 2` offset was wrong.
3. **F2 — horizontal unless explicitly vertical.** If the cell to a label's
   right is usable, it is the value cell, consistent with F4. The below cell
   is inferred only when the right cell is unusable. True vertical intent is
   retained as a future strict xfail until the editor can save an explicit
   **value below** setting.
4. **T6, T10, and T15 — declarations decide table intent.** A labelled cell
   with an empty neighbour is a slot, so `End | _` behaves exactly like
   `Total | _`. Semantic table names, spacer-versus-capacity decisions, and
   whether a closing row belongs to a table cannot come from geometry; those
   owner-intent checks are isolated under strict `needs declared tables`
   xfails for the editor's `Table ↓` / `Table →` declarations.
5. **T9 and T11 — physically possible write truth.** In T9, `Item` remains at
   A1, the anchor of merge A1:A2; A2 cannot also hold text. In T11, record rows
   go around the structural subtotal row and E4 retains its formula; E4 cannot
   hold a record amount and a formula simultaneously.
6. **Watermark audit corpus.** The audit enumerates only committed files under
   `tests/fixtures/acceptance`. Untracked owner material in `local_docs` must
   never change a hermetic test's file, page, or hit counts.
7. **Recorded bank golden.** `Bank_Recon` has no slot for the full account
   number. `Account Number` is therefore recorded in `absent_slots`; the
   available `Account Number Last 4` remains expected. This prevents an
   impossible field from counting as a silent extraction defect.

## Run D adversarial inventory

The comparison baseline is the parent of D6 (`04f8b32`): D1-D5 are present,
but none of D6-D13 is. The audit used 96 committed template grids (all 46
sheets in the acceptance workbook, two production JSON grids, nine gold
templates, five reconstructed round-2 templates, and the 34 scenario
workbooks). No committed non-scenario template changed its slot map. Eight
scenario maps changed:

| Scenario | Exact old → new slot-map difference |
| --- | --- |
| F5 | Added I1 `Status`, H4 `Rate`, H5 `Reviewer`; bands unchanged. |
| F6 | Added C1 `Legal Name`, C3 `Reporting Date`; bands unchanged. |
| F10 | Removed C2 and D2 labelled `=SUM(B1,D1)`; added C2 labelled `Tax`; no bands in either version. |
| F11 | Added B1 `Name`, B2 `Date`; bands unchanged. |
| T6 | Removed extra scalar slots C4/D4 `End left` and H4/I4 `End right` (B4/G4 remain). Added `table_1` A:D and `table_2` F:I, each header row 1 with reserved rows 2-3; old version had no bands. |
| T9 | Replaced band `Debit` (`Debit`, `Credit`) with band `Amount` (`Item`, `Debit`, `Credit`), retaining header row 2 and data rows 3-5. |
| T10 | Added F14 `Total right`; bands unchanged. |
| T15 | Added F2 `Owner`, F3 `Reviewed`; band unchanged. |

Adversarial inputs found strict Run D regressions for: D5 (a correct
all-page Grand Total hides a wrong page subtotal); D6 (a matrix heading with
one empty heading cell becomes scalar fields); D7 (one table with an internal
blank spacer becomes two tables); D8 (a static note beside a table becomes a
field); D10 (a decorative empty merge beside a merged section heading becomes
its slot); D11 (the legitimate exact label `TBD` is erased); and D12 (a
vertical merge over a scalar label invents a band). D1-D4 and D9 survived the
requested ambiguity, routing, repeated-ending, rotation, signed-number, and
right-versus-below probes. `Total due TBD` is correctly not a placeholder.

D13 emitted **36 warnings on 33 of the 96 grids**. Only three warnings point
at a failing audit truth (F10's two formulas and T14's unsupported native table
shape). The other 33 are noise under the recorded rules:

- valid right-hand slots: F5, F6, F7, F12, T10, T15, plus three fields in
  `gold/payslip_transposed`;
- valid structural behavior: T6 shared-row growth and T11's preserved subtotal
  formula;
- owner-approved header-only bands: T2, T13, production
  `bank_statement_101`, round-2 B1/B2, and acceptance sheets Index, W2_Full,
  W2_Register, Pay_Full, Pay_Register, Bank_TxnOnly, Bank_Audit, Invest_Stmt,
  AP_Register, AP_PayList, Rcpt_Register, Rcpt_SalesTicket, Chq_Log, X_Strip,
  X_Bundle, Answers, and RunLog.

## Scenario results (before Run D)

“Parse” requires exact field cells, exact band geometry, and all workbook sheets. “Write” sends a deterministic mocked answer through `run_slot_extraction`, calls the real slot writer, saves the result, reopens it with openpyxl, and checks values, labels, blank answers, formulas, shifts, merges, styles, and applicable native features.

| Scenario | Parses | Writes | Notes |
| --- | --- | --- | --- |
| F1 | yes | yes | Adjacent label/value pairs. |
| F2 | no | no | Vertical slots are changed to B1/D1. |
| F3 | no | no | Separator columns vanish from the text-defined range. |
| F4 | yes | yes | Three same-row pairs are preserved. |
| F5 | no | no | Blank spacer rows do not isolate column-role blocks; several right-side fields disappear. |
| F6 | no | no | Empty merged ranges are not scalar slots. |
| F7 | yes | yes | Cells are correct, but duplicate prompt labels have no section context. |
| F8 | yes | yes | Punctuation and language are not matched semantically. |
| F9 | yes | no | Cells parse, but formats and dropdown validation are lost; date/percent typing is not recovered. |
| F10 | no | no | Formula strings alter geometry and intended fields are missed. |
| F11 | no | no | Placeholder text is static, not a slot. |
| F12 | yes | no | Field cells and merges work; hidden row/column state is lost. |
| F13 | yes | yes | Abbreviated and non-English labels work geometrically. |
| T1 | yes | yes | Five reserved rows and the following total field work when all five rows are filled. |
| T2 | no | yes | Writer fills a header-only band, but parser reports ten reserved rows instead of zero. |
| T3 | yes | yes | Stacked bands with one spacer stay separate. |
| T4 | yes | yes | Adjacent stacked bands shift without collision when capacity is fully used. |
| T5 | yes | yes | Ten rows in the first band push the row-3 header and second band down. |
| T6 | no | no | A blank column between side-by-side headers prevents both bands from being detected. |
| T7 | yes | yes | Borders do not affect parsing and basic borders survive writing. |
| T8 | yes | yes | Bordered and unbordered stacked bands stay distinct. |
| T9 | no | no | The merged `Item` header is omitted; only Debit/Credit form a band. |
| T10 | no | no | A spacer becomes capacity, same-row totals disappear, and totals have no band ownership. |
| T11 | yes | no | The wide band includes the subtotal row, but writing ordinary records overwrites it. |
| T12 | no | no | Transposed inference is unavailable without an editor declaration. |
| T13 | no | yes | Flat-list rows write, but the header-only parser reports ten reserved rows. |
| T14 | no | no | Excel Table metadata is ignored and is not recreated. |
| T15 | no | no | Scalar fields on the table's body rows are excluded and skipped by the writer. |
| T16 | yes | yes | A far-right contiguous header works. |
| T17 | yes | yes | Three two-column section bands and their following total fields work. |
| T18 | no | no | Only the first worksheet participates. |
| T19 | yes | yes | Missing template values stay blank; extra answer keys are ignored. |
| T20 | yes | no | Thirty/300 rows expand, but zero/one row leaves unused reserved rows before the total. |
| T21 | yes | no | Documents stack, but short documents retain internal reserved-row gaps. |

## Prompt ambiguity report

- F7 emits two identical descriptions each for `Name`, `Date`, and `Total`; the merged `Payer` and `Recipient` headings never become scalar sections.
- F2 and F3 emit plausible label-only descriptions while hiding that the chosen cell is wrong, because cell references are absent from prompt prose.
- F5 silently omits several intended scattered slots.
- F6 and F11 emit no descriptions for the intended merged/placeholder slots.
- F10 emits formula text such as `=SUM(B1,D1)` as a row label.
- T6 emits repeated `End left`/`End right` scalar descriptions and no table descriptions.
- T9 emits a `Debit | Credit` table with no `Item` key.
- T12 emits three copies each of `Revenue`, `COGS`, and `Profit`; prompt prose omits the Q1/Q2/Q3 column headers that would distinguish them.
- T15 emits no `Owner` or `Reviewed` description.
- T18 emits no slots from the `Lines` worksheet.

The exact captured slot-description lines are committed in `tests/templates/prompt_capture.json` and checked without a model call.

## Failing scenarios ranked by likely auditor exposure

1. **F5 — scattered groups.** Treat blank spacer rows as block boundaries and preserve every explicit horizontal pair independently.
2. **F9 — formats and validation.** Preserve the slot's native type, number format, and validation while replacing only its value.
3. **T20 — variable row counts.** Expand or contract reserved capacity so the following total touches 0, 1, 30, or 300 written rows without gaps.
4. **T14 — Excel Table objects.** Read the table range as the band and recreate the same named Table over its resized output range.
5. **T18 — multiple sheets.** Build and write a per-sheet slot map while preserving workbook order and sheet-local coordinates.
6. **F11 — placeholders.** Recognize configured placeholder text as an empty slot and clear it when the answer is empty.
7. **F10 — formulas beside fields.** Exclude formulas from label inference, preserve them as formulas, and translate references when rows move.
8. **T6 — side-by-side tables.** Split gapped header runs into independent bands and grow their shared row block without tearing either side apart.
9. **T15 — fields beside tables.** Claim only table columns, not whole rows, so adjacent scalar fields remain addressable and move with the block.
10. **F12 — hidden axes.** Preserve row and column visibility exactly even though it should not influence slot detection.
11. **F2 — vertical fields.** Support an explicit label-above/value-below relationship rather than inventing a right-hand slot.
12. **F3 — separated fields.** Honor an explicitly selected distant empty cell or retain empty separator columns in the template contract.
13. **T11 — internal subtotals.** Model subtotal rows as reserved structural rows and place data around them without overwriting labels or formulas.
14. **T10 — nonstandard totals.** Store each total's explicit relationship and relative position instead of inferring it from nearby text.
15. **T21 — multiple documents.** Size each repeated block from its actual line count and keep a documented inter-document gap with no internal slack.
16. **T13 — flat header-only list.** Represent zero reserved rows honestly while still allowing the writer to append one row per document.
17. **T2 — generic header-only table.** Distinguish zero reserved rows from a ten-row design instead of assigning an undocumented constant.
18. **T9 — multi-level headers.** Flatten merged header levels into complete unique column addresses, including the row-label column.
19. **F6 — merged value cells.** Use the empty merge anchor as the writable slot and preserve the merged output range.
20. **T12 — transposed tables.** Infer or explicitly import record-across-column tables without requiring a separate editor declaration.
