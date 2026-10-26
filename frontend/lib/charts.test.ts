// Run: node --test lib/charts.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { bars, emptyReason, reviewBanner } from "./charts.ts";

test("bars keep the server's numbers and order", () => {
  const b = bars([["Rent", "1250.10"], ["Travel", "20.00"]]);
  assert.deepEqual(b.map(x => [x.label, x.value]), [["Rent", 1250.1], ["Travel", 20]]);
});

test("the banner says how many values still need review", () => {
  assert.equal(reviewBanner({ needs_review: 0 }), null);
  assert.equal(reviewBanner({ needs_review: 1 }), "Includes 1 value that still needs review.");
  assert.match(reviewBanner({ needs_review: 3 }) ?? "", /3 values that still need review/);
});

test("no data gives a reason, never an empty chart", () => {
  assert.match(emptyReason({ currencies: {}, values: 0, left_out_ambiguous: 0, message: null, needs_review: 0 }) ?? "", /Not enough/);
  assert.equal(emptyReason({ currencies: { EUR: { by_category: [], by_month: [], top_items: [], distribution: [], count: 2 } },
    values: 2, left_out_ambiguous: 0, message: null, needs_review: 0 }), null);
});
