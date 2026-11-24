// Run: node --test lib/jobTemplate.test.ts
// Run Q, UI1: picking a template never alters a finished job's results.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { templateOfJob } from "./jobTemplate.ts";

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

test("New extraction sits next to Download Excel in the TOP action bar", () => {
  const src = readFileSync(new URL("../app/extract/page.tsx", import.meta.url), "utf8");
  const top = src.slice(src.indexOf('className="page-title"'), src.indexOf('className="ex-layout"'));
  assert.ok(top.includes("Download Excel"), "Download Excel in the top bar");
  assert.ok(top.includes("<NewExtractionButton"), "New extraction in the top bar");
  assert.equal(src.split("<NewExtractionButton").length - 1, 1, "one New extraction on the page");
  assert.doesNotMatch(src, />New extraction</);
});
