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
