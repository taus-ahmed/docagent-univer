# Template editor capability audit

This is a source audit of the current browser editor, template persistence,
shape parser, and slot-directed Excel writer. It is not an audit of what
`openpyxl` could support in principle. The decisive persisted contract is one
JSON grid containing `cells`, `colWidths`, `merges`, `repeatRows`, and optional
`regions` (`frontend/components/templates/DocAgentSpreadsheet.tsx:51-56`). The
server parses that JSON from the database description field
(`backend/app/services/template_parsing.py:30-46`). The job-download route
loads the JSON and creates a new workbook rather than opening a client's
workbook (`backend/app/api/routes/extract.py:677-699`).

In the table, a check in exactly one of **Yes / Partial / No** is the finding.
“Yes” means the editor contract and export implement the capability, not merely
that Excel itself supports it.

| Capability | Yes | Partial | No | Evidence (file and line) | Experience with an existing Excel template |
| --- | :---: | :---: | :---: | --- | --- |
| Import or upload of `.xlsx` |  |  | ✓ | The editor restores only JSON from `existing.description` (`frontend/components/templates/TemplateEditor.tsx:126-134`) and saves JSON through create/update (`frontend/components/templates/TemplateEditor.tsx:312-329`; `backend/app/api/routes/templates.py:170-237`). | They cannot upload the workbook. They must redraw it manually, so the original workbook is not a round-trip source of truth. |
| Formulas: stored, evaluated, and retained in export |  | ✓ |  | Every cell value is only a string (`frontend/components/templates/DocAgentSpreadsheet.tsx:13-15`), and the “formula bar” explicitly edits cell text (`frontend/components/templates/DocAgentSpreadsheet.tsx:793-825`). Static strings are copied to the new sheet (`backend/app/services/excel_slot.py:568-582`), so a leading `=` can reach Excel, but the parser warns that it treats such a cell as a label and never calculates it (`backend/engine/template_shape.py:1167-1190`). | A manually retyped static formula may remain a formula for Excel to calculate when opened, but DocAgent does not evaluate it and may interpret it as a label/slot boundary. Formula-driven layouts are unsafe, especially around expanding tables. |
| Several sheets or tabs in one template |  |  | ✓ | `SheetSaveData` describes one grid, not a sheets collection (`frontend/components/templates/DocAgentSpreadsheet.tsx:51-56`), and the editor mounts one `SheetComp` (`frontend/components/templates/TemplateEditor.tsx:558-568`). | Only one sheet can be recreated. Other workbook tabs, references, and sheet-specific layouts cannot be represented. |
| Data validation or dropdowns |  |  | ✓ | The exhaustive cell/save types contain value, basic style, merge, width, and region metadata only (`frontend/components/templates/DocAgentSpreadsheet.tsx:7-56`); the style/export path applies no validation objects (`backend/app/services/excel_cells.py:714-740`). | Existing dropdowns disappear because the workbook cannot be imported, and the editor offers no way to rebuild them. |
| Merged cells |  | ✓ |  | Merges are first-class saved ranges (`frontend/components/templates/DocAgentSpreadsheet.tsx:16-24,51-56`) and are recreated during export (`backend/app/services/excel_cells.py:465-490`). A merge touching a dynamic table band is deliberately skipped (`backend/app/services/excel_cells.py:468-484`). | Ordinary manually recreated merges survive. A merge over rows belonging to an expanding table is omitted to avoid hiding data, so the exported layout can differ visibly. |
| Cell styles and borders |  | ✓ |  | The editor supports a limited style vocabulary (`frontend/components/templates/DocAgentSpreadsheet.tsx:7-11`). Export applies font, fill, alignment, wrapping, and `borderAll` (`backend/app/services/excel_cells.py:714-740`), but does not apply the saved `strike` or `borderOuter` fields. | Basic formatting can be redrawn. Arbitrary Excel themes/styles are not imported, and even two exposed editor choices (strike and outer border) do not survive export. |
| Number formats and percentages |  |  | ✓ | The saved cell type has no number-format/type property (`frontend/components/templates/DocAgentSpreadsheet.tsx:13-15,51-56`). Export derives a format only from an extracted numeric source string (`backend/app/services/excel_cells.py:305-326,354-400`), while percentages are intentionally left as text (`backend/app/services/excel_cells.py:238-248`). | Existing accounting/custom/percentage formats cannot be carried in. Some extracted money receives a newly inferred display format, but that is not preservation of the template and percentages are not real numeric percentage cells. |
| Dates as real Excel dates |  |  | ✓ | All editor values are strings (`frontend/components/templates/DocAgentSpreadsheet.tsx:13-15`); the shared writer only coerces supported amounts to numbers and otherwise writes the supplied text (`backend/app/services/excel_cells.py:305-330`). | Dates look like text and do not reliably sort, filter, or calculate as Excel date serials. Existing date formats are lost. |
| Column widths | ✓ |  |  | Dragged widths are serialized (`frontend/components/templates/DocAgentSpreadsheet.tsx:183-201`) and honored in preference to autofit (`backend/app/services/excel_cells.py:51-76`). | They can manually reproduce column widths; untouched columns are automatically sized from content rather than preserving an original workbook width. |
| A label above with the value below | ✓ |  |  | The shape parser assigns the cell below when the cell to the right is unavailable and the lower cell is unclaimed (`backend/engine/template_shape.py:1085-1117`). | This layout works when the geometry is unambiguous. If both right and below are plausible, the right-hand slot wins and the template warning reports the ambiguity. |
| Declared tables, with rows or columns as the record direction | ✓ |  |  | The editor contract exposes `orientation: "rows" | "columns"` (`frontend/components/templates/DocAgentSpreadsheet.tsx:45-49`); the parser implements both ordinary and transposed declared bands (`backend/engine/template_shape.py:296-418`). | They can redraw a table and explicitly say whether records grow downward or sideways, avoiding reliance on automatic detection. |
| Reserved rows and overflow handling | ✓ |  |  | The writer uses the document's actual row count, grows when actual rows exceed the reservation, compacts when fewer are present, and retains blank rows outside the band (`backend/app/services/excel_slot.py:306-318,507-525`). | A 30-row reserved area can grow to 64 records without truncation; unused reserved rows collapse and content below shifts accordingly. This is dynamic output, not pixel-for-pixel preservation. |
| Native Excel tables |  |  | ✓ | Declared regions are DocAgent JSON geometry (`backend/engine/template_shape.py:296-350`), and the persisted schema has no native table name/style/range metadata (`frontend/components/templates/DocAgentSpreadsheet.tsx:45-56`). | A structured Excel Table cannot be imported or rebuilt as a native table. The export contains ordinary cells, without table filters, structured references, or table styles. |
| Hidden rows or columns |  |  | ✓ | The saved grid has column widths but no row/column visibility metadata (`frontend/components/templates/DocAgentSpreadsheet.tsx:51-56`); export sets widths only (`backend/app/services/excel_cells.py:56-76`). | Hidden helper ranges become impossible to represent. If recreated as visible cells, they will show; otherwise they are omitted. |
| Protected cells or sheets |  |  | ✓ | Neither `CellStyle` nor `SheetSaveData` has locked/protection properties (`frontend/components/templates/DocAgentSpreadsheet.tsx:7-11,51-56`), and the style writer sets no protection (`backend/app/services/excel_cells.py:714-740`). | Input cells, formulas, and the sheet cannot retain their locked/unlocked or protected state. |
| Images or logos |  |  | ✓ | The persisted contract contains no media or anchor metadata (`frontend/components/templates/DocAgentSpreadsheet.tsx:51-56`), and template export starts from a new empty workbook (`backend/app/api/routes/extract.py:677-699`). | Company logos, signatures, seals, and other workbook images cannot be imported or recreated through the editor and will not appear in the output. |

## Five gaps most likely to block a paying client

1. **No `.xlsx` import or workbook round trip.** This forces a paying client to
   rebuild the asset before discovering which workbook features cannot survive.
   Smallest closing change: add a template-upload endpoint and UI action that
   reads a workbook into a versioned template artifact; retain the original
   workbook as the export base rather than flattening it immediately to cells.

2. **Only one sheet.** Operational workbooks commonly split detail, summary,
   instructions, and lookup data across tabs. Smallest closing change: replace
   the single-grid root with `sheets[]` (name plus current grid payload), add a
   tab selector, and have the slot writer target each declared sheet.

3. **Formulas are text to DocAgent, not a dependable template feature.** A
   summary formula can be mistaken for a label and is not evaluated during
   validation. Smallest closing change: give cells distinct `value` and
   `formula` fields, exclude formulas from label detection, and preserve/adjust
   formulas when dynamic bands move. Excel may remain the calculation engine.

4. **Excel value types and formats are not preserved.** Real dates, numeric
   percentages, and client-defined number formats become strings or newly
   inferred formats. Smallest closing change: add `valueType` and
   `numberFormat` to the cell contract and write typed values plus the exact
   format code.

5. **Workbook controls and brand assets are stripped.** Validation lists,
   protection, hidden helpers, native tables, and logos are often part of the
   deliverable rather than decoration. Smallest closing change: once export is
   based on the uploaded workbook, preserve these untouched by default and only
   mutate declared output cells/ranges; expose editor controls later where
   clients need to create new ones.

