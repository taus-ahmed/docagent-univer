// Run: node --test lib/reviewPages.test.ts
// Overnight E2: the review dialog moves between every page of the document.
import { test } from "node:test";
import assert from "node:assert/strict";
import { firstValueOn, pageList, pageNav } from "./reviewPages.ts";

test("mammoth_2pg: a page with no value is still listed (page count 2)", () => {
  assert.deepEqual(pageList([1], 2), [1, 2]);
});

test("previous / next step through the pages and say where you are", () => {
  const first = pageNav([1], 1, 2);
  assert.equal(first.prev, null);
  assert.equal(first.next, 2);
  assert.equal(first.label, "Page 1 of 2");
  const second = pageNav([1], 2, 2);
  assert.equal(second.prev, 1);
  assert.equal(second.next, null);
  assert.equal(second.label, "Page 2 of 2");
});

test("a one-page document has no previous or next", () => {
  const nav = pageNav([1], 1, 1);
  assert.equal(nav.prev, null);
  assert.equal(nav.next, null);
});

test("an unknown page count keeps the server's list", () => {
  assert.deepEqual(pageList([2, 4], null), [2, 4]);
  assert.equal(pageNav([2, 4], 4).prev, 2);
});

test("the slot list jumps to the first value printed on the page", () => {
  const values = [{ page: 1 }, { page: 1 }, { page: 2 }, { page: 2 }];
  assert.equal(firstValueOn(values, 2), 2);
  assert.equal(firstValueOn(values, 3), -1);
});
