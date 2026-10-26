// Run: node --test lib/templateForm.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { leaveWarning, validateTemplate } from "./templateForm.ts";

const cells = { "0,0": { value: "Invoice No" } };

test("a good template has no errors", () => {
  assert.deepEqual(validateTemplate({ name: "Invoices", docType: "invoice", cells }), []);
});

test("errors name their field in plain words", () => {
  const e = validateTemplate({ name: " ", docType: "other", customDocType: "Pay Order", cells: {} });
  assert.deepEqual(e.map(x => x.field), ["name", "docType", "grid"]);
  assert.match(e[0].message, /name/);
});

test("duplicate names, bad id_type and bad locale are caught before saving", () => {
  const e = validateTemplate({
    name: "invoices", docType: "invoice", existingNames: ["Invoices"],
    cells: { ...cells, "0,1": { value: "", id_type: "passport" } }, locale: "english",
  });
  assert.deepEqual(e.map(x => x.field), ["name", "grid", "locale"]);
  assert.match(e[1].message, /B1/);
});

test("the leave warning only when something is unsaved", () => {
  assert.equal(leaveWarning(false), null);
  assert.match(leaveWarning(true) ?? "", /unsaved/);
});
