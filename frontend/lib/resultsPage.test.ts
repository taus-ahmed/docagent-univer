import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const extract = source("../app/extract/page.tsx");
const history = source("../app/history/page.tsx");

test("both pages use the same left column and leave download actions out of their headers", () => {
  const shared = source("../components/extract/JobResultsLayout.tsx");
  const sidebar = shared.slice(shared.indexOf("<aside"), shared.indexOf("</aside>"));
  const labels = ["Template used", "Status", "Download Organized", "Download Excel", "<NewExtractionButton", "Download with audit columns", "Download ZIP"];
  let last = -1;
  for (const label of labels) {
    const next = sidebar.indexOf(label);
    assert.ok(next > last, label);
    last = next;
  }
  for (const page of [extract, history]) {
    assert.match(page, /<JobResultsLayout\b/);
    assert.doesNotMatch(page, /Download Excel|Download Organized|Download with audit columns/);
  }
});

test("regular stays the primary clean download and audit is a separate action", () => {
  const shared = source("../components/extract/JobResultsLayout.tsx");
  assert.match(shared, /kind === "regular" \? "btn-primary" : "btn-secondary"/);
  assert.match(shared, /templateExport\(job\.id, kind === "audit"\)/);
  assert.match(shared, /organizedExport\(job\.id\)/);
  assert.match(shared, /role="alert"/);
  assert.doesNotMatch(shared, /type="checkbox"/);
});

test("the model name remains available in the results header", () => {
  assert.match(extract, /Extracted by \{jobModels\(results\)\}/);
});

test("failure reasons remain available in Extract and History", () => {
  assert.match(extract, /jobErrorText\(jobStatus\.error_message/);
  assert.match(history, /failureLine\(job\)/);
});

test("the status box retains the branch's plain status meanings", () => {
  assert.match(source("../components/extract/JobResultsLayout.tsx"), /plainStatus\(job\)/);
});

test("ZIP follows the job's documents even after reopening from History", () => {
  const shared = source("../components/extract/JobResultsLayout.tsx");
  assert.match(shared, /Math\.max\(job\.total_docs, documentCount\) > 1/);
});

test("the preview follows the active job instead of the template selector", () => {
  assert.match(extract, /const previewTemplate = activeJobId \? jobTemplate : selectedTemplate/);
  assert.match(extract, /<TemplatePreview template=\{previewTemplate\} \/>/);
});

test("fresh Extract orders the four cards in reading order", () => {
  const start = extract.indexOf('className="extract-workspace"');
  assert.ok(start >= 0);
  const layout = extract.slice(start);
  let last = 0;
  for (const label of ["Documents uploader", "Additional options", "Template picker", "Template layout preview"]) {
    const next = layout.indexOf(label, last);
    assert.ok(next > last, label);
    last = next;
  }
});
