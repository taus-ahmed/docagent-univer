# Progress

## Review-3 fixes

Codex reviewed `3343071` (integration/ocr-hardening) and returned REVISE.
One commit per item, each with a regression test that fails before the fix.

- **F1 word-order amounts** — `cheque_amounts.parse_words_amount` read
  "fifty cents one dollar" as 50.01. The subunit must now close the amount:
  a main-unit word after the subunit word, two subunit words, a number on
  both sides of the subunit word, or number words after a `/100` fraction
  give `unit_order` (unreadable, flagged). `tests/test_amount_unit_order.py`
  enumerates all 24 orders of number/unit/number/subunit for every main-unit
  and subunit word the parser knows and reads each by role.
- **F2 export precision** — `coerce_cell_value` turned the shared parser's
  Decimal into a float, so 123456789012345.67 exported as ...345.7.
  `excel_cells.excel_number` gives the float only when the value has at most
  15 significant digits (where a double round-trips to exactly the printed
  decimal); beyond that the printed text is written and `precision_flag`
  puts a comment on the cell, kept ahead of the provenance comment. The
  charts sheet uses the same rule for its totals. The flat, combined and
  per-file writers already wrote text and are pinned unrounded.
  `tests/test_export_precision.py` runs every writer.
- **F3 legacy export** — the layout, table, form, mixed and table-rows
  fallback writers each stripped `$`/`,` and called float(), so an ambiguous
  "1,234" became a number. Every number write now goes through
  `excel_cells.put_extracted` → `coerce_cell_value` (the shared parser with
  the document's own hint): ambiguous amounts and identifiers stay text,
  long numbers stay text and are flagged, numbers carry the printed notation
  as a number format. The mixed writer's "only amount labels become numbers"
  rule is kept (`numeric=False` otherwise). `_document_hint_of` moved to
  `excel_cells.document_hint_of` (excel_slot keeps the name).
