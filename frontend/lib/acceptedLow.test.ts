// Run: node --test lib/acceptedLow.test.ts
// Run Q, Q13: accepting values flagged Low is counted and asked first.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { acceptAllConfirmation, acceptedAfterLowText } from "./review.ts";

test("accepted-after-Low is said, with its count", () => {
  assert.equal(acceptedAfterLowText(3), "3 values accepted after being flagged Low");
  assert.equal(acceptedAfterLowText(1), "1 value accepted after being flagged Low");
  assert.equal(acceptedAfterLowText(0), "");
  assert.equal(acceptedAfterLowText(undefined), "");
});

test("mark-document-reviewed asks first, naming how many Low values it accepts", () => {
  const q = acceptAllConfirmation({ low: 4, needs_review: 6 });
  assert.match(q, /accepts 4 values flagged Low as they stand/);
  assert.match(q, /and 2 other values that need review/);
  assert.equal(acceptAllConfirmation({ low: 0, needs_review: 3 }), "");
});

test("the review dialog's accept-all calls the confirmation before marking", () => {
  const src = readFileSync(new URL("../components/extract/ReviewPanel.tsx", import.meta.url), "utf8");
  const i = src.indexOf("const markDocument");
  const ask = src.indexOf("acceptAllConfirmation(doc.summary)", i);
  const mark = src.indexOf('scope: "document"', i);
  assert.ok(ask > i && ask < mark, "the confirmation must come before the request");
});
