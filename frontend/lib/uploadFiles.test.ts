// Run: node --test lib/uploadFiles.test.ts
// Review-3 F10: a PDF password belongs to ONE listed file, and goes with it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  addFiles, clearPasswords, filesOf, passwordsOf, removeFile, setPassword,
} from "./uploadFiles.ts";

const file = (name: string) => ({ name, size: 1 }) as unknown as File;
let n = 0;
const id = () => `t${++n}`;

test("removing a file removes its password", () => {
  let l = addFiles([], [file("a.pdf"), file("b.pdf")], id);
  l = setPassword(l, l[0].id, "s3cret");
  l = removeFile(l, l[0].id);
  assert.deepEqual(passwordsOf(l), [null]);
  assert.ok(!JSON.stringify(l).includes("s3cret"));
});

test("re-adding the same file name does not restore the old password", () => {
  let l = addFiles([], [file("a.pdf")], id);
  const first = l[0].id;
  l = setPassword(l, first, "s3cret");
  l = removeFile(l, first);
  l = addFiles(l, [file("a.pdf")], id);
  assert.notEqual(l[0].id, first);
  assert.equal(l[0].password, "");
  assert.deepEqual(passwordsOf(l), [null]);
});

test("each file keeps its own password, in upload order", () => {
  let l = addFiles([], [file("a.pdf"), file("b.pdf"), file("c.png")], id);
  l = setPassword(l, l[1].id, "pw-b");
  assert.deepEqual(filesOf(l).map(f => f.name), ["a.pdf", "b.pdf", "c.png"]);
  assert.deepEqual(passwordsOf(l), [null, "pw-b", null]);
});

test("a name already listed is not added twice", () => {
  let l = addFiles([], [file("a.pdf")], id);
  l = setPassword(l, l[0].id, "keep");
  l = addFiles(l, [file("a.pdf"), file("b.pdf")], id);
  assert.deepEqual(filesOf(l).map(f => f.name), ["a.pdf", "b.pdf"]);
  assert.equal(l[0].password, "keep");
});

test("clearing wipes every password and keeps the files", () => {
  let l = addFiles([], [file("a.pdf"), file("b.pdf")], id);
  l = setPassword(setPassword(l, l[0].id, "x"), l[1].id, "y");
  const c = clearPasswords(l);
  assert.deepEqual(passwordsOf(c), [null, null]);
  assert.equal(filesOf(c).length, 2);
  assert.equal(clearPasswords(c), c);              // nothing to clear: same list
});

// ── the page itself ──────────────────────────────────────────────────────────

const page = readFileSync(new URL("../app/extract/page.tsx", import.meta.url), "utf8");

test("the page keys the list by entry id and wipes passwords on submit, cancel and reset", () => {
  assert.match(page, /key=\{id\}/);
  assert.doesNotMatch(page, /passwords\[f\.name\]/);
  assert.ok((page.match(/setPending\(clearPasswords\)/g) || []).length >= 2, "submit and cancel");
  assert.match(page, /function reset\(\) \{\s*setPending\(\[\]\)/);
});

test("the password field is never autofilled, stored or put in a URL", () => {
  const input = page.slice(page.indexOf('type="password"') - 20, page.indexOf('type="password"') + 600);
  // "new-password", not "off": Chrome ignores off on a password (Recheck R5)
  assert.match(input, /autoComplete="new-password"/);
  for (const line of page.split("\n")) {
    if (/password|pending/i.test(line)) {
      assert.doesNotMatch(line, /localStorage|sessionStorage|router\.(push|replace)|history\.|searchParams|location\./, line);
    }
  }
  assert.doesNotMatch(readFileSync(new URL("./uploadFiles.ts", import.meta.url), "utf8")
    .replace(/\/\*\*[\s\S]*?\*\//g, ""), /localStorage|sessionStorage|history|location/);
});
