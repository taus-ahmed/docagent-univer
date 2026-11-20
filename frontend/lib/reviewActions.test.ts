// Run: node --test lib/reviewActions.test.ts
// Run G, G5: every review action the dialog and the grid offer, as the
// request it sends (the server contract is tests/test_review_flow_spec.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NotReviewable, actionDone, actionsFor, addRowBody, gridAction, historyLine,
  reviewBody, tablesOf, valueEntry,
} from "./reviewActions.ts";

const field = { kind: "field" as const, ref: "B2" };
const cell = { kind: "cell" as const, ref: null, table: "items", row: 0,
               row_id: "row-1", column: "Amount" };

test("Accept as is: a field sends its ref and the disposition", () => {
  assert.deepEqual(reviewBody([valueEntry(field, "accepted_as_is")]),
                   { values: [{ ref: "B2", disposition: "accepted_as_is" }] });
});

test("Accept as is on a table value names its column and row id, never the whole row", () => {
  assert.deepEqual(valueEntry(cell, "accepted_as_is"),
                   { table: "items", row: 0, row_id: "row-1", column: "Amount",
                     disposition: "accepted_as_is" });
});

test("Correct sends the corrected value with the disposition, in one entry", () => {
  assert.deepEqual(valueEntry(field, "corrected", "Human correction"),
                   { ref: "B2", disposition: "corrected", value: "Human correction" });
  assert.deepEqual(valueEntry(cell, "corrected", "12.00"),
                   { table: "items", row: 0, row_id: "row-1", column: "Amount",
                     disposition: "corrected", value: "12.00" });
  assert.throws(() => valueEntry(field, "corrected"), NotReviewable);
});

test("Mark empty sends confirmed_empty and no value", () => {
  assert.deepEqual(valueEntry({ kind: "field", ref: "B3" }, "confirmed_empty"),
                   { ref: "B3", disposition: "confirmed_empty" });
});

test("a value with no address cannot be reviewed (no guessing a slot)", () => {
  assert.throws(() => valueEntry({ kind: "field", ref: null }, "accepted_as_is"), NotReviewable);
  assert.throws(() => valueEntry({ kind: "cell", ref: null, table: "items" }, "accepted_as_is"),
                NotReviewable);
});

test("only an unresolved value offers the three actions, in order", () => {
  assert.deepEqual(actionsFor({ ...field, resolved: false }).map(a => a.label),
                   ["Accept as is", "Correct", "Mark empty"]);
  assert.deepEqual(actionsFor({ ...field, resolved: true }), []);
  assert.deepEqual(actionsFor({ kind: "category", ref: null, resolved: false }), []);
  assert.equal(actionDone("corrected"), "Corrected and accepted");
});

test("Add row: only the table's own columns, blanks dropped, reason passed on", () => {
  const ed = { slot_map: { tables: [{ name: "items", columns: [
    { header: "Description", key: "Description" }, { header: "Amount", key: "Amount" }] }] } };
  const [spec] = tablesOf(ed);
  assert.deepEqual(spec, { name: "items", columns: ["Description", "Amount"] });
  assert.deepEqual(addRowBody(spec, { Description: " Added item ", Amount: "5.00", Colour: "red" },
                              "att-1"),
                   { values: { Description: "Added item", Amount: "5.00" }, attention_id: "att-1" });
  assert.deepEqual(addRowBody(spec, { Description: "x", Amount: "" }), { values: { Description: "x" } });
  assert.equal(addRowBody(spec, { Description: "  " }), null);
  assert.deepEqual(tablesOf({}), []);
});

test("grid: one click selects, double-click edits a value cell, Review opens the dialog", () => {
  assert.equal(gridAction("Invoice Number", "click"), "select");
  assert.equal(gridAction("Invoice Number", "double"), "edit");
  assert.equal(gridAction("_review", "click"), "review");
  assert.equal(gridAction("_review", "double"), "none");
  assert.equal(gridAction("_has_rows", "click"), "rows");
  assert.equal(gridAction("_filename", "click"), "select");
  assert.equal(gridAction("_filename", "double"), "none");      // not editable
});

// The components are not rendered here (no DOM test library, and none may be
// added): these read their source and check each action is wired to the
// request builders above, the same way lib/passwordFields.test.ts checks forms.
import { readFileSync } from "node:fs";
const panel = readFileSync(new URL("../components/extract/ReviewPanel.tsx", import.meta.url), "utf8");
const grid = readFileSync(new URL("../components/extract/ResultsGrid.tsx", import.meta.url), "utf8");

test("ReviewPanel: the three flagged-value actions go through valueEntry, one request each", () => {
  assert.match(panel, /actionsFor\(v\)\.map/);
  assert.match(panel, /reviewBody\(\[valueEntry\(v, d, value\)\]\)/);
  assert.match(panel, /if \(a\.id === "corrected"\) startEdit\(v, "correct"\);\s*else dispose\(v, a\.id\);/);
  assert.match(panel, /if \(editMode === "correct"\) dispose\(v, "corrected", text\);/);
  assert.doesNotMatch(panel, /table: String\(v\.table\), row: Number\(v\.row\) \}/);   // no row-wide accept
});

test("ReviewPanel: line-item cells are edited one cell at a time; Add row and History are wired", () => {
  assert.match(panel, /extractApi\.editCell\(/);
  assert.match(panel, /reviewApi\.addRow\(jobId, doc\.doc_id, spec\.name, body\)/);
  assert.match(panel, /addRowBody\(spec, addValues, addReason \|\| null\)/);
  assert.match(panel, /reviewApi\.history\(jobId, doc\.doc_id\)/);
  assert.match(panel, /historyLine\(ev\)/);
  assert.match(panel, /aria-label="History"/);
});

test("ResultsGrid: no row click opens the dialog; a Review button does", () => {
  assert.doesNotMatch(grid, /onRowClicked/);
  assert.match(grid, /colId: "_review"/);
  assert.match(grid, /gridAction\("_review", "click"\) === "review"/);
  assert.match(grid, /singleClickEdit=\{false\}/);
});

test("history: who, when, where, old and new, in one plain line", () => {
  assert.equal(historyLine({ kind: "field", by: "ana", at: "2026-11-20T10:00:00Z", ref: "B2",
                             old: "Machine value", new: "History value" }),
               `ana, 2026-11-20T10:00:00Z — B2 edited: "Machine value" → "History value"`);
  assert.equal(historyLine({ kind: "cell", by: "ana", at: "t", table: "items", row: 0,
                             column: "Amount", old: "10.00", new: "12.00", disposition: "corrected" }),
               `ana, t — items row 1: Amount corrected: "10.00" → "12.00"`);
  assert.equal(historyLine({ kind: "field", by: "ana", at: "t", ref: "B3", old: "x", new: "",
                             disposition: "confirmed_empty" }),
               `ana, t — B3 marked empty: "x" → (empty)`);
  assert.equal(historyLine({ kind: "field", by: "ana", at: "t", ref: "B2", value: "v",
                             disposition: "accepted_as_is" }),
               `ana, t — B2 accepted as is ("v")`);
  assert.equal(historyLine({ kind: "add_row", by: "ana", at: "t", table: "items",
                             values: { Description: "Added", Amount: "5.00" } }),
               "ana, t — added a row to items: Description: Added · Amount: 5.00");
});
