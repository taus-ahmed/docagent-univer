// Run: node --test lib/jobModel.test.ts
// Overnight M2: the job detail names the model that answered.
import { test } from "node:test";
import assert from "node:assert/strict";
import { jobModels } from "./jobModel.ts";

test("distinct models, in order, blanks ignored", () => {
  assert.equal(jobModels([{ model_used: "gemini-2.5-flash-001" }, { model_used: null },
                          { model_used: "gemini-2.5-flash-001" }, { model_used: "vision_direct" }]),
               "gemini-2.5-flash-001, vision_direct");
  assert.equal(jobModels([]), "");
});

import { failureLine } from "./jobModel.ts";

test("Run Q, Q12: a failed job always shows a reason line in the list", () => {
  assert.equal(failureLine({ status: "failed", error_message: "1 of 1 document(s) failed. Extraction failed: the model's answer was cut off." }),
               "1 of 1 document(s) failed. Extraction failed: the model's answer was cut off.");
  assert.match(failureLine({ status: "failed", error_message: null }), /no reason was recorded/);
  assert.equal(failureLine({ status: "completed", error_message: "x" }), "");
  assert.ok(failureLine({ status: "partial", error_message: "y".repeat(300) }).length <= 140);
});
