// Run: node --test lib/resultsPage.test.ts
// Run Q, UI3: the results page's actions, in one consistent place.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../app/extract/page.tsx", import.meta.url), "utf8");

test("Download Excel is the primary button and downloads the CLEAN file", () => {
  const i = page.indexOf("Download Excel");
  const btn = page.lastIndexOf("<button", i);
  assert.match(page.slice(btn, i), /btn-primary/);
  assert.match(page.slice(btn, i), /templateExport\(activeJobId, false\)/);
});

test("the audit version is a secondary button, not a checkbox", () => {
  assert.match(page, /Download with audit columns/);
  assert.doesNotMatch(page, /type="checkbox" checked=\{includeAudit\}/);
  const i = page.indexOf("Download with audit columns");
  assert.match(page.slice(page.lastIndexOf("<button", i), i), /btn-secondary/);
});

test("the model name and the failure reason are shown on the results page", () => {
  assert.match(page, /Extracted by \{jobModels\(results\)\}/);
  assert.match(page, /jobErrorText\(jobStatus\.error_message/);
});

test("Download, ZIP, audit and New extraction share one export row, at the top", () => {
  const row = page.indexOf('className="export-row"');
  assert.ok(row < page.indexOf('className="ex-layout"'), "the export row is the top action bar");
  const end = page.indexOf("</div>", page.indexOf("Extracted by", row));
  const block = page.slice(row, end);
  for (const t of ["Download Excel", "Download ZIP", "NewExtractionButton", "Download with audit columns"])
    assert.ok(block.includes(t), t);
});

// Run Q Phase 3, UI3 (docs/UI_BACKLOG.md, results page)
test("the job's status is said in plain words, as History says it", () => {
  assert.match(page, /import \{[^}]*plainStatus[^}]*\} from "@\/lib\/jobModel"/);
  assert.match(page, /plainStatus\(jobStatus/);
});

test("Download ZIP follows the job's documents, not the emptied upload list", () => {
  assert.doesNotMatch(page, /\{files\.length > 1 && \(\s*<button[^>]*>\s*[^]*?Download ZIP/);
  assert.match(page, /jobDocCount > 1/);
});

test("a shown job replaces the template picker with the template it used", () => {
  const picker = page.indexOf("{/* Template picker */}");
  assert.ok(picker > 0);
  assert.match(page.slice(picker, picker + 400), /!activeJobId \?/);
  assert.match(page, /Template used/);
});

test("the empty state previews the job's template, not the picker's, once a job is open", () => {
  assert.match(page, /const previewTemplate = activeJobId \? jobTemplate : selectedTemplate/);
  assert.match(page, /<TemplatePreview template=\{previewTemplate\} \/>/);
});
