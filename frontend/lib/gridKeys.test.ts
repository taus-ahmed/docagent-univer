// Run: node --test lib/gridKeys.test.ts
// Part A7: the template editor's keyboard rules, as data.
import { test } from "node:test";
import assert from "node:assert/strict";
import { editKey, gridOwnsKey, selectKey } from "./gridKeys.ts";

const mid = { col: 3, cols: 26 };

test("Tab and Shift+Tab move between cells and never insert a tab", () => {
  assert.deepEqual(selectKey({ key: "Tab", shift: false, ...mid }), { kind: "move", dr: 0, dc: 1 });
  assert.deepEqual(selectKey({ key: "Tab", shift: true, ...mid }), { kind: "move", dr: 0, dc: -1 });
});

test("Tab at the edge lets focus leave the grid (no focus trap)", () => {
  assert.deepEqual(selectKey({ key: "Tab", shift: false, col: 25, cols: 26 }), { kind: "leave" });
  assert.deepEqual(selectKey({ key: "Tab", shift: true, col: 0, cols: 26 }), { kind: "leave" });
});

test("while editing: Tab commits and moves right, Shift+Tab left, Enter down, Escape cancels", () => {
  assert.deepEqual(editKey({ key: "Tab", shift: false }), { kind: "commit", dr: 0, dc: 1 });
  assert.deepEqual(editKey({ key: "Tab", shift: true }), { kind: "commit", dr: 0, dc: -1 });
  assert.deepEqual(editKey({ key: "Enter", shift: false }), { kind: "commit", dr: 1, dc: 0 });
  assert.deepEqual(editKey({ key: "Enter", shift: true }), { kind: "commit", dr: -1, dc: 0 });
  assert.deepEqual(editKey({ key: "Escape", shift: false }), { kind: "cancel" });
  assert.deepEqual(editKey({ key: "a", shift: false }), { kind: "none" });
});

test("the grid only takes keys when focus is inside it and no dialog is open", () => {
  assert.equal(gridOwnsKey({ focusInGrid: true, dialogOpen: false, editing: false }), true);
  assert.equal(gridOwnsKey({ focusInGrid: false, dialogOpen: false, editing: false }), false);
  assert.equal(gridOwnsKey({ focusInGrid: true, dialogOpen: true, editing: false }), false);
  assert.equal(gridOwnsKey({ focusInGrid: true, dialogOpen: false, editing: true }), false);
});
