# Gold labels

One flat JSON file per document in `labels/`. These are **independent ground
truth**, produced by reading each PDF's text directly (pdfplumber) and
cross-checking the arithmetic (line items sum to their totals, statement
debits/credits reconcile to the closing balance, net pay = earnings −
deductions, etc.). They were NOT produced by running the extraction pipeline.

**Never regenerate these files from engine output.** When the engine's output
schema changes, change `tests/harness/adapter.py` instead.

## Label file schema

```jsonc
{
  "document_id": "INV-2024-0031",
  "document_type": "sales_invoice",      // prompt-registry key
  "pdf": "INV-2024-0031.pdf",            // in tests/test_pdfs/
  "template": "invoice.json",            // in tests/gold/templates/ (runner hint)
  "fields": {                            // field name -> expected value
    "Invoice Number": "INV-2024-0031",   //   null = the document has NO value here;
    "Sales Tax": 966.71                  //   an extracted value for a null field is a hallucination
  },
  "field_types": {                       // money | date | number | string
    "Invoice Number": "string",          //   omitted fields default to "string"
    "Sales Tax": "money"
  },
  "tables": {                            // table name -> list of row objects
    "line_items": [ {"Description": "…", "Qty": 40, "Unit Price": 185.0, "Amount": 7400.0} ]
  },
  "table_types": {                       // per-table column types
    "line_items": {"Qty": "number", "Unit Price": "money", "Amount": "money"}
  },
  "uncertain": [                         // OPEN labeling-policy questions a human must
    "…"                                  // resolve; a wrong label is worse than a missing
  ],                                     // one. Empty once decided — see policy below.
  "notes": "free text about the document"
}
```

## Labeling policy

- Values are recorded **as the document states them**, even when the document
  is internally inconsistent (BS-2024-Q1 does not balance — that is a property
  of the fixture, and the label records what is printed).
- Money values are plain numbers; currency symbols and thousands separators
  are the scorer's job to strip from the *extracted* side.
- Amounts printed in accounting parentheses — `($3,240.00)` — are recorded as
  **negative** numbers (policy P2). Amounts printed positive under a "Less:"
  label are recorded **positive**, as printed (policy P1).
- Dates are recorded ISO (`2024-01-15`). Dates printed without a year
  (`03/15` in statement/expense rows) are recorded as printed; the date
  comparator matches them year-agnostically.
- `null` means "the document genuinely has nothing here" (e.g. the Debit cell
  of a credit transaction). This is what makes hallucinations measurable.

## Resolved labeling policy

Decided by the repo owner on 2026-08-17, in response to the six questions the
first labeling pass raised. These are binding for all future labels; label
files carry the policy id in their `notes`, and every `uncertain` array is now
empty. **The governing principle is P0: gold records what the document
prints, in the field's own region. Interpreting or transforming that value is
the product's job downstream, not part of reading it.**

| id | question | decision |
|---|---|---|
| **P0** | general | Gold = the value **as printed**, in that field's own region of the page. |
| **P1** | `Less:` contra lines printed positive with no parentheses and no minus — BS-2024-Q1 `Less: Accum. Depreciation $108,500`; IS-2024-Q4 `Less: Returns $28,600`, `Less: Closing Inventory $724,000` | **Positive, as printed.** Sign inference from the "Less:" prefix is an accounting transform, not a reading task — even though the printed section totals only reconcile when these are subtracted. |
| **P2** | amounts printed in accounting parentheses — payslip deductions, `Federal Income Tax ($3,240.00)`, `Total ($7,070.30)` | **Negative.** Parentheses *are* explicit negative notation, unlike a "Less:" prefix. This also matches the pipeline's own `_normalize_value`, which already converts `(2.85)` → `-2.85`. |
| **P3** | a name field whose printed text also carries a title — PO-2024-0018 `Authorised By:` / `Janet Wu – VP Operations` | **Full printed string**, `"Janet Wu – VP Operations"`. Per P0, gold is what that field's region prints. CHQ-001847's signature block prints `Janet Wu` alone, so its label is name-only by the same rule — the two differ because the documents differ. |
| **P5** | an identifier printed in two forms — CHQ-001847 header `No: CHQ-001847` vs MICR `…C 001847D` | **The human-facing field form**, `"CHQ-001847"`, not the bare MICR serial. |
| **P6** | print-security decoration around a value — CHQ-001847 `Eight Thousand Four Hundred Ten and 00/100 *** U.S. DOLLARS ***` | **Full printed string including the decoration.** P0 wins over "strip the filler"; the `***`/`U.S. DOLLARS` are on the page. |
| **P7** | a section heading followed by label/amount lines — is it a TABLE of rows or a LIST of fields? BS-2024-Q1 `CURRENT ASSETS`; IS-2024-Q4 `REVENUE`, `COST OF GOODS SOLD`, `OPERATING EXPENSES` | **A table, when the heading is followed by 3 or more label/amount lines.** Decided 2026-08-23. The first pass labelled the balance sheet as 5 tables and the income statement — the same shape — as 25 flat fields, so the same document class was measured two ways and an engine could not satisfy both. Counting rule: the section's **closing total** (`Total Current Assets`, `Net Revenue`, `Total COGS`) is a FIELD, not a row, and it counts toward the 3. **A single label/amount pair under a heading is a FIELD, not a one-row table** (decided 2026-08-23) — a table needs at least two rows to be one, and a lone pair under a heading is just a labelled value that happens to sit below a title. IS-2024-Q4 `OTHER INCOME` prints one line, so `Interest Income` is a field. The engine enforces the same threshold in `shape_inference._MIN_SECTION_ROWS` and the >= 2 data-row check, so gold and the detector agree by construction. Statement-level totals under no heading (`GROSS PROFIT`, `TOTAL ASSETS`, `NET INCOME`) are fields. |
| **P8** | a cheque's signing party and its two amounts — CHQ-001847 `Payer Name`, `Amount` | **`Drawer Name` and `Amount in Figures`.** Decided 2026-08-23, and this one corrected GOLD rather than the engine. The party who writes and signs a cheque is the DRAWER (UCC Art. 3 and ordinary banking usage); "Payer" is colloquial and is confusable with the payee. A cheque states its amount twice, in figures and in words, and they can disagree — which is the whole reason both are printed — so a field called just "Amount" does not say which one was read. The engine's canonical vocabulary (`engine/vocabulary.py`) already used both standard terms; the labels did not, and the labels were wrong. Values unchanged: the rename carried them across and asserted they were identical. |

(There is no P4: the two payslips raised one shared question, answered by P2.)

P8 renamed two CHQ-001847 fields and `templates/cheque.json` with them. It is the first policy where the ENGINE was right and gold was corrected to match, rather than the other way round — recorded in `engine/vocabulary.py::GOLD_DIVERGENCE` so the reason survives the rename.

P7 moved 16 of IS-2024-Q4's 25 gold fields into 3 tables. **No printed value changed** — the relabel copied values across rather than re-reading them, and asserted that the flattened before/after sets were identical. `templates/income_statement.json` was rebuilt to match, so a `missed` outcome still means "asked and not returned".

Consequences for scoring: an extraction that returns the *other* candidate in
each case scores **`near`**, not `wrong` — the scorer treats sign-only money
differences and substring/containment string differences as near misses.
`near` counts against headline accuracy and is reported separately, so these
choices move numbers between the `correct` and `near` columns but never hide a
disagreement.

## Templates (`templates/`)

The spreadsheet-grid templates the runner extracts with — the same
`SheetSaveData` JSON shape a template saved from the editor stores in
`ColumnTemplate.description`. One per document type, requesting exactly the
fields/tables the labels cover, so a `missed` outcome always means "asked and
not returned". The engine's own classifier decides the extraction route
(`template_type`); the harness observes and reports that route, it does not
force one. `templates/cbm/` holds the Gemini-produced cell binding map for
each template (the artifact production computes at template-save time),
recorded once and committed.
