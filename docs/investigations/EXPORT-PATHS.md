# Export paths and their review marks (2026-10-23)

Every function that produces a file a user downloads, and how it marks a value
a person still owes a look. "Marks" means, per value: a fill and a comment
naming the status and reasons; per sheet: a "Review status" column whose header
counts what still needs review; per workbook: a Legend sheet. The status of
every value comes from `app.core.review.value_status`, the function the review
screen uses — inline in the slot writer, through `app.core.export_marks.SheetMarks`
everywhere else. `tests/test_every_export_marks.py` runs every writer below over
a fixture holding a value of every status and fails if any non-verified value
is written unmarked or any clean one is marked.

| Entry point | Writer | Reached by | Before this round | Now |
|---|---|---|---|---|
| `GET /api/jobs/{id}/export` | `_write_slot_excel` (via `_write_excel`, `template_type=slot`) | every PDF with a template | marked (Part 2) | unchanged |
| same | `_write_inferred_sheets` → `_write_slot_excel` | no template, inferred | marked (Part 2) | unchanged |
| same | `_write_form_excel` (+ `_write_table_rows_fallback`) | image uploads with a template (`labeled`/`mixed` from the vision path), legacy jobs | a pale-yellow tint on `low` only; nothing for unverified, medium, review_required; Legend only | **marked** (SheetMarks) |
| same | `_write_table_excel` | legacy / image, `primary_mode=table` | none | **marked** |
| same | `_write_mixed_excel` | legacy / image, `primary_mode=mixed` | `low` tint only | **marked** |
| same | `_write_layout_excel` | `structural`, or legacy results with `layout_sections` (image vision answers can carry them) | none; its values were not even counted in the Legend | **marked**; counted via `review.export_values` |
| same | `_write_flat_table` | nothing to build a sheet from | none | **marked** |
| `GET /api/jobs/{id}/export/zip` | the same writers, one workbook per document | | as above | as above |
| `POST /api/export/combined` | `export._build_excel(per_file=False)` | `ExportPanel.tsx` (not mounted on any page today) | a row tint when the document needs review; no per-value mark; no Legend | **marked**, Review status column, Legend |
| `POST /api/export/perfile` | `export._build_excel(per_file=True)` | same | a "Confidence" column only | **marked**, Review status column, Legend |
| `GET /api/demo/sample-docs/{name}` | `FileResponse` of a bundled demo PDF | demo sample panel | not an export of results | n/a |

Not found: no CSV or JSON export of results, no e-mail helper, no client-side
spreadsheet generation (the frontend only saves blobs the API returns). The
confirmation before a download (`lib/confirm-export.ts`) now also guards the
combined and per-file buttons in `ExportPanel.tsx`.

Rules the legacy writers follow, where their data is thinner than a slot result:

* **An image upload is never verified** (`review._image_level`): its values are
  `unverified` whatever level a legacy record carries, unless edited.
* **A legacy level the vocabulary does not know** (`medium`, or none — table
  rows from the vision path carry no `_confidence`) is `unknown`, which needs
  review.
* **A value the form writer computes** (a template formula it evaluates) has no
  level of its own and is marked `unknown`.
* **A cell written twice** (the legacy layout writer does this) is judged by the
  value left in it; the earlier mark is removed.
* Legacy layout values are counted and marked in exports but are not listed on
  the review screen: no review route can address them.
