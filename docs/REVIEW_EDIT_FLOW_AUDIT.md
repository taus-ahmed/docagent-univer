# Review and edit flow audit

Scope: source-only audit of the current frontend and backend. No server, browser,
model, or remote service was run. I therefore could not verify the owner's exact
deployed build, browser event sequence, account permissions, network response, or
whether the affected record is a current slot result or a legacy result without
cell references.

## (a) Where a reviewer can change a value today

There are two edit surfaces:

1. Scalar result columns in the main AG Grid are declared editable, and the page
   tells the user to double-click a cell
   ([`ResultsGrid.tsx:248-254`](../frontend/components/extract/ResultsGrid.tsx#L248),
   [`ResultsGrid.tsx:353-355`](../frontend/components/extract/ResultsGrid.tsx#L353)).
2. In the review dialog, select a value and use **Edit (e)**. The dialog renders
   an input and Save button and supports both a field-slot PATCH and a table-cell
   PATCH
   ([`ReviewPanel.tsx:106-129`](../frontend/components/extract/ReviewPanel.tsx#L106),
   [`ReviewPanel.tsx:321-355`](../frontend/components/extract/ReviewPanel.tsx#L321)).

The most likely reason inline editing appears not to work is an event collision:
the grid opens the review dialog on the first row click, while editing requires a
double-click. There is no guard for clicks on an editable value cell
([`ResultsGrid.tsx:390-403`](../frontend/components/extract/ResultsGrid.tsx#L390)).
The expanded line-item table is display-only
([`ResultsGrid.tsx:79-117`](../frontend/components/extract/ResultsGrid.tsx#L79)).
In the dialog, only the active value exposes Edit, and a legacy field with no
`ref` is rejected as uneditable there
([`ReviewPanel.tsx:109-120`](../frontend/components/extract/ReviewPanel.tsx#L109)).

There is also a semantic surprise: after Save, the value is immediately
classified as resolved `edited`, so the **Accept** button disappears. The code
does not implement a separate "edit, then accept the edit" step
([`review.py:250-267`](../backend/app/core/review.py#L250),
[`ReviewPanel.tsx:345-355`](../frontend/components/extract/ReviewPanel.tsx#L345)).

## (b) What happens to an edit

The frontend sends either:

- `PATCH /api/jobs/{job}/docs/{doc}/fields/{ref}` with `{value}`, or
- `PATCH /api/jobs/{job}/docs/{doc}/rows/{table}/{row}` with `{column, value}`
  ([`api.ts:505-524`](../frontend/lib/api.ts#L505),
  [`extract.py:982-1020`](../backend/app/api/routes/extract.py#L982)).

A field edit updates all stored copies: `extracted_fields[ref]`, the confidence
map (`edited`), provenance (`edited` and first `original_value`), and the
label-keyed `extracted_data` projection
([`edits.py:36-56`](../backend/app/services/edits.py#L36)). A table edit changes
the row value and records `_edited` and `_original`
([`edits.py:150-175`](../backend/app/services/edits.py#L150)).

The complete result is serialized back into `DocumentResult.extraction_json`.
An append-only `edit_log` inside that same JSON records actor, UTC time, target,
old value, and new value; there is no separate edit-log table
([`edits.py:178-213`](../backend/app/services/edits.py#L178),
[`edits.py:238-258`](../backend/app/services/edits.py#L238),
[`models.py:142-154`](../backend/app/models/models.py#L142)). The save also
changes the relational `reviewed`, `reviewed_by`, and `needs_review` columns,
but its decision considers only open completeness items, not other unresolved
flagged values, and it does not set `reviewed_at`
([`edits.py:242-258`](../backend/app/services/edits.py#L242)). The raw model
response is not changed.

Every template download is rebuilt from the current `DocumentResult` rows, and
the writers call `get_extracted_data()` before writing fields and table cells
([`extract.py:659-709`](../backend/app/api/routes/extract.py#L659),
[`excel_slot.py:373-392`](../backend/app/services/excel_slot.py#L373),
[`excel_slot.py:663-748`](../backend/app/services/excel_slot.py#L663)). Therefore
a re-download uses the edit. I found no flow that carries edits into a brand-new
extraction job, so I could not verify that "regenerate" in that sense preserves
them.

## (c) Accept, mark reviewed, and flagged-item disposition

**Accept** posts a value review mark. For a field it stores
`field_provenance[ref].reviewed`. For a table value the request contains only
table and row, not column, so accepting one displayed cell stores `_reviewed` on
the whole row
([`ReviewPanel.tsx:91-104`](../frontend/components/extract/ReviewPanel.tsx#L91),
[`review.py:171-202`](../backend/app/api/routes/review.py#L171)). Reasons and
machine flags are retained; the mark merely makes the value resolved.

**Mark document reviewed** stores `review.document_reviewed` in
`extraction_json`. That one mark makes every value read as reviewed
([`review.py:290-318`](../backend/app/core/review.py#L290),
[`review.py:171-177`](../backend/app/api/routes/review.py#L171)). It is refused
while any completeness `attention[]` item is open. Those items must first be
given either `confirmed_absent` or `entered_manually`; the choice, note, actor,
and time remain on the item
([`review.py:490-550`](../backend/app/core/review.py#L490),
[`review.py:259-290`](../backend/app/api/routes/review.py#L259)). The
`entered_manually` choice does not verify that an edit or missing row was
actually added.

There is a second, unused frontend client method for `POST .../approve`. That
backend route changes only relational review columns, not the JSON review mark,
so the review screen/export can still regard values as unresolved. No frontend
call site uses it
([`api.ts:527-529`](../frontend/lib/api.ts#L527),
[`extract.py:1022-1038`](../backend/app/api/routes/extract.py#L1022)).

## (d) What the downloaded Excel reflects

Edits are written as current values. Review markings are also exported: edited
cells are lavender; reviewed formerly-flagged cells are pale green; unresolved
low/unverified/empty-flagged cells retain warning fills. Each mark has a comment,
and every workbook gets a Legend
([`review.py:553-585`](../backend/app/core/review.py#L553),
[`excel_cells.py:596-674`](../backend/app/services/excel_cells.py#L596)). The
default template download omits Source and Review status columns, but keeps
fills, comments, and Legend; `include_audit=true` adds those columns
([`extract.py:626-640`](../backend/app/api/routes/extract.py#L626)). The comments
say "reviewed by a person" but do not identify who or when.

`DRAFT` has narrower meaning than general review state. It is added to the
filename and Legend only while a completeness `attention` reason is open
([`excel_cells.py:622-642`](../backend/app/services/excel_cells.py#L622),
[`excel_cells.py:677-685`](../backend/app/services/excel_cells.py#L677),
[`extract.py:715-719`](../backend/app/api/routes/extract.py#L715)). It disappears
as soon as all such reasons receive dispositions. Mark-document-reviewed is
blocked until then. A workbook with unresolved low/unverified values but no
completeness reason is not named DRAFT; its cells and Legend still show the
unresolved review state.

## (e) Gaps for a review-only-to-approve product

- **Inline edit:** present for scalar cells and in the modal, but the grid click
  collision makes it unreliable; the expanded line-item view is read-only.
- **Accept a flagged value:** present for fields, but table-cell Accept silently
  accepts the entire row. An edit auto-resolves, so there is no explicit
  accept-after-edit action.
- **Confirm a flagged empty as truly empty:** generic Accept can mark it
  reviewed, but there is no field-level `confirmed_empty` disposition or note.
  `confirmed_absent` applies only to a separate completeness item.
- **Add a missing row:** no UI or dedicated endpoint. The legacy whole-document
  PUT can technically receive a changed row list, but that is not a safe or
  discoverable review operation
  ([`edits.py:114-138`](../backend/app/services/edits.py#L114)).
- **Undo:** `_original` and `edit_log` retain evidence, but there is no undo API
  or UI.
- **Who changed what:** the JSON contains edit events and review/disposition
  stamps, but `GET .../review` reduces stamps to booleans and the UI/export does
  not expose the actor, time, old value, or new value
  ([`review.py:110-154`](../backend/app/api/routes/review.py#L110)).
- **One approval truth:** edit save, JSON review marks, relational review flags,
  the unused approve route, and DRAFT do not all use the same definition of
  complete.

## (f) Smallest ordered change list

1. Remove the grid click conflict: use an explicit Review action, allow value
   double-click to edit, and make table cells editable in the same dialog.
2. Define explicit value dispositions (`accepted_as_is`, `corrected`,
   `confirmed_empty`) and make table review marks cell-specific. Make edit plus
   disposition one atomic request, or keep an edit unresolved until accepted.
3. Add a dedicated add-row operation with stable row identity and connect
   `entered_manually` completeness dispositions to the row/value actually added.
4. Expose the existing edit/review history, then add version/CAS protection and
   undo as a new audit event rather than deleting history.
5. Retire or repair the legacy approve route and derive database flags, final
   approval, export marks, and DRAFT from the same stored open-obligation state;
   add HTTP/UI/export tests for the complete workflow.

## (g) Target contract pinned by tests

[`tests/test_review_flow_spec.py`](../tests/test_review_flow_spec.py) chooses and
pins the following API contract. It deliberately keeps the legacy approve
route, but requires it to share the same state as review rather than introducing
a second approval truth.

| Rule | Target behavior | Today |
| --- | --- | --- |
| 1 | Each value stores `accepted_as_is`, `corrected`, or `confirmed_empty`, with actor/time and an edit-log event. | Strict xfail: marks contain actor/time but no disposition or acceptance event. |
| 2 | A `corrected` review entry changes the value, logs old/new, and accepts it in one transaction. | Strict xfail: edit and review are separate operations. |
| 3 | A table review mark addresses one stable row id and one column. | Strict xfail: `_reviewed` applies to the entire row. |
| 4 | `confirmed_empty` removes that slot's unresolved flag and exports a clean empty cell. | Strict xfail: no field-level empty disposition exists. |
| 5 | `POST .../rows/{table}` creates a stable row, logs it, resolves its completeness item, and recomputes or re-flags totals. | Strict xfail: the endpoint does not exist. |
| 6 | JSON review, relational columns, legacy approve, listing state, and DRAFT derive from the same open obligations. | Strict xfail: DRAFT ignores unresolved flagged values and legacy approve updates a different state. |
| 7 | `GET .../history` returns actor, time, old/new, and field/cell identity. | Strict xfail: history is stored but has no read endpoint. |
| 8 | Re-downloaded Excel contains final corrected/confirmed values and no stale review styling. | Strict xfail: the review call cannot apply the target dispositions atomically. |
