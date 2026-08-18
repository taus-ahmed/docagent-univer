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
  "uncertain": [                         // labeling-policy questions a human should resolve;
    "…"                                  // a wrong label is worse than a missing one
  ],
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
  **negative** numbers. Amounts printed positive under a "Less:" label are
  recorded **positive** (as printed). Both conventions are flagged in
  `uncertain` where they occur.
- Dates are recorded ISO (`2024-01-15`). Dates printed without a year
  (`03/15` in statement/expense rows) are recorded as printed; the date
  comparator matches them year-agnostically.
- `null` means "the document genuinely has nothing here" (e.g. the Debit cell
  of a credit transaction). This is what makes hallucinations measurable.

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
