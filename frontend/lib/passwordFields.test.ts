// Recheck R5: every password field says what it is to the browser.
//
// Chrome ignores autocomplete="off" on a password input, so the PDF password
// box was still offered for saving and autofill, and the admin's "Password"
// box for ANOTHER user carried no hint at all — Chrome could fill in the
// signed-in admin's own password there. A field for a password the user
// types fresh is "new-password"; only sign-in and "current password" fields
// are "current-password". "off" is never used.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));

function tsxFiles(dir: string): string[] {
  return readdirSync(dir).flatMap(n => {
    const p = join(dir, n);
    if (n === "node_modules" || n.startsWith(".")) return [];
    return statSync(p).isDirectory() ? tsxFiles(p) : p.endsWith(".tsx") ? [p] : [];
  });
}

/** Every <input …> whose type can be "password", with its file. */
function passwordInputs(): { file: string; tag: string }[] {
  const out: { file: string; tag: string }[] = [];
  for (const f of [...tsxFiles(join(ROOT, "app")), ...tsxFiles(join(ROOT, "components"))]) {
    const src = readFileSync(f, "utf8");
    for (const m of src.matchAll(/<input\b[\s\S]*?\/>/g)) {
      if (/type=(?:"password"|\{[^}]*"password"[^}]*\})/.test(m[0])) out.push({ file: f, tag: m[0] });
    }
  }
  return out;
}

test("there are password fields to check", () => {
  assert.ok(passwordInputs().length >= 5);
});

test("no password field uses autocomplete off, and each names its purpose", () => {
  for (const { file, tag } of passwordInputs()) {
    const m = tag.match(/autoComplete="([^"]*)"/);
    assert.ok(m, `${file}: a password input without autoComplete`);
    assert.ok(["new-password", "current-password"].includes(m![1]), `${file}: autoComplete="${m![1]}"`);
  }
});

test("the PDF password and the admin's password for another user are new-password", () => {
  const pdf = passwordInputs().filter(i => i.file.endsWith(join("extract", "page.tsx")));
  const admin = passwordInputs().filter(i => i.file.endsWith(join("admin", "page.tsx")));
  assert.equal(pdf.length, 1);
  assert.equal(admin.length, 1);
  for (const { tag } of [...pdf, ...admin]) assert.match(tag, /autoComplete="new-password"/);
});
