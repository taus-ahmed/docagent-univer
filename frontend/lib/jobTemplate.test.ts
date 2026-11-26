// Run: node --test lib/jobTemplate.test.ts
// Run Q, UI1: picking a template never alters a finished job's results.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { templateOfJob, templateUsedLabel } from "./jobTemplate.ts";

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

test("only a reported null schema_id means no template was used", () => {
  assert.equal(templateUsedLabel({ schema_id: "7" }, T[1]), "W-2");
  assert.match(templateUsedLabel({ schema_id: null }, null), /^No template/);
  assert.equal(templateUsedLabel({ schema_id: "99" }, null), "Template #99 (name unavailable)");
  assert.equal(templateUsedLabel({ schema_id: "99" }, null, true), "Loading template…");
  assert.equal(templateUsedLabel({}, null), "Template information unavailable");
});

// Phase 3 UI1 rework: New extraction is the same action as the top-right
// one — a fresh extract page. It never re-runs or alters the current job.
const btn = readFileSync(new URL("../components/extract/NewExtractionButton.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("./api.ts", import.meta.url), "utf8");

test("New extraction opens the fresh extract page, never a re-run", () => {
  assert.match(btn, /href="\/extract"/);
  assert.doesNotMatch(btn, /rerun/i);
  assert.doesNotMatch(btn, /<select/);
  assert.doesNotMatch(btn, /No template|Run as new job/);
  assert.doesNotMatch(api, /rerun/i);
});

test("the fresh page has no files, no result and the template picker reset", () => {
  const src = readFileSync(new URL("../app/extract/page.tsx", import.meta.url), "utf8");
  const body = src.slice(src.indexOf("function reset()"), src.indexOf("}", src.indexOf("function reset()")));
  for (const t of ["setPending([])", "setResults([])", "setActiveJobId(null)", "setSelectedTemplate(null)"])
    assert.ok(body.includes(t), t);
});

test("both pages use the one shared New extraction action", () => {
  const shared = readFileSync(new URL("../components/extract/JobResultsLayout.tsx", import.meta.url), "utf8");
  assert.equal(shared.split("<NewExtractionButton").length - 1, 1);
  for (const p of ["../app/extract/page.tsx", "../app/history/page.tsx"]) {
    const src = readFileSync(new URL(p, import.meta.url), "utf8");
    assert.match(src, /<JobResultsLayout\b/, p);
    assert.doesNotMatch(src, /<NewExtractionButton\b/, p);
  }
});
