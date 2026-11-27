# Reviewer structure API (Run T2, Stage 6)

Backend only. A reviewer corrects the **Organized** layout of one document
(`GET /api/jobs/{id}/export?layout=organized`) without retyping it: move a
cell, merge two cells, split a cell, put words in another table column, or
leave a line out / bring it back. This document is the contract for the
frontend task; no frontend exists yet.

Code: `backend/app/api/routes/structure.py` (routes),
`backend/engine/structure_edits.py` (the edits), tests
`tests/http/test_t2_structure_edits.py`.

## Model

* A document's layout is rebuilt every time from three stored things, in
  this order: its **words** (perception, stored at job time), its **plan**
  (a stored model plan, or the geometry's plan), and its **edits**. The same
  three always give the same sheet - the export, the `GET` below and every
  later rebuild agree.
* Edits are an ordered list stored with the words
  (`document_results.perception_json` -> `structure_edits`). Each edit:
  `{id, op, page, ...op fields..., by, when}` - `by` is the username, `when`
  UTC ISO-8601. Edits are never rewritten; removing one is `DELETE`.
* **Plan edits** (`ignore_line`, `unignore_line`, `reassign_column`) change
  what the plan says, so they survive any later re-placement.
* **Cell edits** (`move_cell`, `merge_cells`, `split_cell`) act on the
  placed grid of one page, addressed `A1`-style **per page** (each page is its
  own block; row 1 is the page's first row). On creation the server records
  the **word ids** the addressed cell(s) held; when the layout is rebuilt, an
  edit whose cell no longer holds those words is **not applied** and is
  reported (`edit_results`, and a flag in the export's `Layout check` sheet)
  - it is never re-aimed at other words.
* No edit changes any word's text. A merged cell is the two cells' words in
  reading order; a split cell is the same words in two cells. Values are
  re-typed the way placement types them (dates, money).
* A record stored before page words were kept is read once from its stored
  file for the `GET`.

## Permissions

| route | action (`app/core/permissions.py`) |
|---|---|
| `GET .../structure` | `job.view` |
| `POST .../structure/edits`, `DELETE .../structure/edits/{edit_id}` | `job.review` |

Another firm's job or document answers exactly like a missing one (404), as
every route (`tests/http/test_tenant_isolation_all_routes.py`).

## `GET /api/jobs/{job_id}/docs/{doc_id}/structure`

The layout as it stands, with every edit applied.

```json
{
  "pages": [
    {"page": 1,
     "cells":   [{"cell": "A6", "text": "Alpha", "word_ids": ["p1w7"],
                  "kind": "value", "edited": false}],
     "regions": [{"id": "r3", "kind": "table", "line_ids": ["p1l2", "..."],
                  "anchor": "A5", "columns": 2}],
     "lines":   [{"id": "p1l6", "text": "Stray footer words",
                  "left_out": true, "reason": "reviewer: footer"}]},
    {"page": 2, "skipped": true, "cells": [], "regions": [], "lines": []}
  ],
  "edits":        [{"id": 1, "op": "ignore_line", "page": 1, "line_id": "p1l6",
                    "reason": "footer", "by": "jroe", "when": "2026-11-27T10:00:00+00:00"}],
  "edit_results": [{"id": 1, "op": "ignore_line", "applied": true, "why": null}],
  "flags":   ["page 1: ..."],
  "skipped": []
}
```

* `cells[].cell` is the address within its page block.
* `regions[].kind`: `title`, `kv` (label/value), `table`, `form`, `note`,
  `side`, `furniture`, `form_copy`; `columns` for tables (count, 0-based in
  edits).
* `lines[].left_out` with `reason`: a line the layout leaves out (note text,
  furniture, markup, a reviewer's ignore, ...).

404 `This document has no stored layout`: no words stored and no file.

## `POST /api/jobs/{job_id}/docs/{doc_id}/structure/edits`

One edit. Answer **201** with `{"edit": {...stored edit...}, ...the GET body...}`.

| op | fields | effect |
|---|---|---|
| `ignore_line` | `page`, `line_id`, `reason` | the line leaves its region; listed with reason `reviewer: <reason>` |
| `unignore_line` | `page`, `line_id` | a left-out line comes back as a label/value region of its own |
| `reassign_column` | `page`, `region` (a table id), `word_ids`, `column` (0-based) | those words are placed in that column of that table, on their own row |
| `move_cell` | `page`, `cell`, `to` | the cell moves; `to` must be empty |
| `merge_cells` | `page`, `cells: [a, b]` | `b`'s words join `a` (reading order); `b` is emptied |
| `split_cell` | `page`, `cell`, `at` (1-based count of words kept), `to` (optional; default the cell to the right) | words from `at` on go to `to`, which must be empty |

Examples:

```json
{"op": "ignore_line", "page": 1, "line_id": "p1l6", "reason": "footer"}
{"op": "move_cell", "page": 1, "cell": "A6", "to": "F30"}
{"op": "merge_cells", "page": 1, "cells": ["A1", "B1"]}
{"op": "split_cell", "page": 1, "cell": "A1", "at": 2, "to": "H1"}
{"op": "reassign_column", "page": 1, "region": "r3", "word_ids": ["p1w11"], "column": 0}
```

**422** `{"detail": {"message": ..., "errors": [...]}}` - the edit is NOT
stored when:

* its shape is wrong (unknown `op`, a missing field, an address that is not
  `A1`-style, `at` < 1, a negative `column`), or the page does not exist;
* it cannot apply to the layout as it stands: the line is not on the page,
  the line is not left out (`unignore_line`), the region is not a table, the
  column is past the table's last, a target cell is not empty, `at` is not
  inside the cell's words, the cells are the same cell.

Word ids for cell edits are taken by the server from the layout at the
moment the edit is made; a client never sends them for cell edits.

## `DELETE /api/jobs/{job_id}/docs/{doc_id}/structure/edits/{edit_id}`

Removes one edit; answers **200** with the GET body. **404** `Edit not
found`. Later edits stay; one that depended on the removed edit (a cell
moved by it, say) is then reported as not applied, never guessed.

## Export

`GET /api/jobs/{job_id}/export?layout=organized` applies the stored edits.
An edit that no longer applies is listed in the workbook's `Layout check`
sheet (`reviewer edit N (op) not applied - why`). The default export (the
extraction's own sheet) is not affected by structure edits.

## Not in this run

* No frontend (a separate task).
* Edits are per document, not per job or template; they do not learn.
* Re-running a job stores new words and a new plan; edits made on the old
  record are not carried to the new one.
