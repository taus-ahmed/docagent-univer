// Run: node --test lib/jobTemplate.test.ts
// Run Q, UI1: picking a template never alters a finished job's results.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { rerunBody, templateOfJob } from "./jobTemplate.ts";

const T = [{ id: 3, name: "Invoice" }, { id: 7, name: "W-2" }];

test("the job's own template, by its schema id", () => {
  assert.equal(templateOfJob({ schema_id: "7" }, T)?.name, "W-2");
  assert.equal(templateOfJob({ schema_id: 3 }, T)?.name, "Invoice");
});

test("no template, an unknown id or no job: null, never the picker", () => {
  assert.equal(templateOfJob({ schema_id: null }, T), null);
  assert.equal(templateOfJob({ schema_id: "99" }, T), null);
  assert.equal(templateOfJob(undefined, T), null);
});

test("the results grid is given the job's template, not the picker's", () => {
  const src = readFileSync(new URL("../app/extract/page.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(src, /<ResultsGrid[^>]*template=\{selectedTemplate\}/);
  assert.match(src, /<ResultsGrid[^>]*template=\{jobTemplate\}/);
});

test("New extraction is offered next to Download Excel on both pages", () => {
  for (const p of ["../app/extract/page.tsx", "../app/history/page.tsx"]) {
    const src = readFileSync(new URL(p, import.meta.url), "utf8");
    assert.match(src, /NewExtractionButton/, p);
  }
});

test("a re-run asks for a template id or explicitly none", () => {
  assert.deepEqual(rerunBody(5), { template_id: 5 });
  assert.deepEqual(rerunBody(null), { template_id: null });
});
