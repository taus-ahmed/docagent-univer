// Run: node --test lib/review.test.ts   (Node 22.18+ strips the types itself)
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BADGES, badgeFor, boxToPercent, exportWarning, fieldColumns, filterDocs,
  reasonText, recordLabel, stepOpen, type ReviewDoc, type ReviewValue,
} from "./review.ts";

function v(label: string, status: ReviewValue["status"], resolved: boolean,
           extra: Partial<ReviewValue> = {}): ReviewValue {
  return { kind: "field", ref: label, label, value: "x", level: null, page: 1,
           source: "x", status, reasons: [], review_required: !resolved,
           reviewed: false, resolved, ...extra };
}

function doc(id: number, values: ReviewValue[], extra: Partial<ReviewDoc> = {}): ReviewDoc {
  const open = values.filter(x => !x.resolved);
  return {
    doc_id: id, filename: `batch.pdf [${id} of 3]`, original_filename: "batch.pdf",
    document_index: id, document_count: 3, document_type: "cheque", pages: [id],
    needs_review: open.length > 0, document_reviewed: false, failed: false, error: "",
    values,
    summary: { values: values.length, needs_review: open.length,
               low: open.filter(x => x.status === "low").length,
               unverified: open.filter(x => x.status === "unverified").length,
               empty_flagged: open.filter(x => x.status === "empty_flagged").length },
    ...extra,
  };
}

const DOCS = [
  doc(1, [v("Amount", "verified", true), v("Payee", "low", false)]),
  doc(2, [v("Amount", "unverified", false), v("Date", "verified", true)]),
  doc(3, [v("Amount", "verified", true)]),
  doc(4, [], { failed: true }),
];

test("every status has a word and a colour pair", () => {
  for (const [k, b] of Object.entries(BADGES)) {
    assert.ok(b.text.length > 0, k);
    assert.match(b.fg, /^#[0-9a-f]{6}$/);
    assert.match(b.bg, /^#[0-9a-f]{6}$/);
  }
});

test("a confident value that still owes a look is not shown as clean", () => {
  assert.equal(badgeFor({ status: "verified", resolved: true, reviewed: false }).text, "Verified");
  assert.equal(badgeFor({ status: "verified", resolved: false, reviewed: false }).text,
               "Verified · review");
  assert.equal(badgeFor({ status: "low", resolved: true, reviewed: true }).text, "Low · reviewed");
});

test("filters", () => {
  assert.deepEqual(filterDocs(DOCS, "all").map(d => d.doc_id), [1, 2, 3, 4]);
  assert.deepEqual(filterDocs(DOCS, "needs_review").map(d => d.doc_id), [1, 2, 4]);
  assert.deepEqual(filterDocs(DOCS, "low").map(d => d.doc_id), [1]);
  assert.deepEqual(filterDocs(DOCS, "unverified").map(d => d.doc_id), [2]);
});

test("columns are the union of field labels, first-seen order", () => {
  assert.deepEqual(fieldColumns(DOCS), ["Amount", "Payee", "Date"]);
});

test("record label carries the k of N name and the pages", () => {
  assert.equal(recordLabel(DOCS[1]), "batch.pdf [2 of 3] · p.2");
  assert.equal(recordLabel({ filename: "a.pdf", pages: [1, 2, 3] }), "a.pdf · p.1–3");
  assert.equal(recordLabel({ filename: "a.pdf", pages: [] }), "a.pdf");
});

test("an unknown reason code is shown, not hidden", () => {
  const t = reasonText("brand_new", { ocr_origin: { label: "Scan", tooltip: "t" } });
  assert.match(t.label, /brand_new/);
  assert.equal(reasonText("ocr_origin", { ocr_origin: { label: "Scan", tooltip: "t" } }).label, "Scan");
  assert.match(reasonText("x", undefined).label, /x/);
});

test("next / previous open value wraps", () => {
  const vals = [v("a", "low", false), v("b", "verified", true), v("c", "unverified", false)];
  assert.equal(stepOpen(vals, -1, 1), 0);
  assert.equal(stepOpen(vals, 0, 1), 2);
  assert.equal(stepOpen(vals, 2, 1), 0);
  assert.equal(stepOpen(vals, 0, -1), 2);
  assert.equal(stepOpen([v("b", "verified", true)], 0, 1), -1);
});

test("boxes scale to the image", () => {
  assert.deepEqual(boxToPercent([0, 0, 306, 396], 612, 792),
                   { left: "0%", top: "0%", width: "50%", height: "50%" });
});

test("the export warning counts what is open, and is silent when nothing is", () => {
  assert.equal(exportWarning({ values: 3, needs_review: 0, low: 0, unverified: 0, empty_flagged: 0 }), null);
  const w = exportWarning({ values: 3, needs_review: 2, low: 1, unverified: 1, empty_flagged: 0 });
  assert.match(w ?? "", /^2 values still need review \(1 low, 1 unverified/);
});

test("a declared rule's reason names the rule", () => {
  const map = { rule_failed: { label: "Template rule failed", tooltip: "t" } };
  assert.equal(reasonText("rule_failed:lines_sum", map).label, "Template rule failed (lines_sum)");
  assert.match(reasonText("other:thing", map).label, /^Needs review/);
});
