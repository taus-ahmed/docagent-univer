// Run: node --test lib/session-gate.test.ts
// AUTH-ADJACENT: reload / deep link / expiry behaviour of the protected layout.
import { test } from "node:test";
import assert from "node:assert/strict";
import { gateDecision, loginUrl, safeNext, tokenValid } from "./session-gate.ts";

// The store's initializeFromStorage, reduced to its decision: read the token,
// then the state the layout sees.
function afterReading(token: string | null, exp: string | null, now: number,
                      meOk = true) {
  const authenticated = tokenValid(token, exp, now) && meOk;
  return gateDecision(true, authenticated);
}

test("before the stored session is read, nothing is decided", () => {
  assert.equal(gateDecision(false, false), "wait");
  assert.equal(gateDecision(false, true), "wait");
});

test("a reload with a valid session stays on the page", () => {
  assert.equal(afterReading("tok", String(2_000), 1_000), "allow");
  assert.equal(afterReading("tok", null, 1_000), "allow");
});

test("no session redirects to login", () => {
  assert.equal(afterReading(null, null, 1_000), "redirect");
});

test("an expired session redirects to login", () => {
  assert.equal(afterReading("tok", String(1_000), 1_000), "redirect");
  assert.equal(afterReading("tok", String(999), 1_000), "redirect");
});

test("a token the server rejects redirects to login", () => {
  assert.equal(afterReading("tok", String(2_000), 1_000, false), "redirect");
});

test("a deep link keeps its destination through login", () => {
  const url = loginUrl("/extract", "?job=12");
  assert.equal(url, "/login?next=%2Fextract%3Fjob%3D12");
  const next = new URLSearchParams(url.split("?")[1]).get("next");
  assert.equal(safeNext(next), "/extract?job=12");
});

test("login itself and the root carry no destination", () => {
  assert.equal(loginUrl("/login", ""), "/login");
  assert.equal(loginUrl("/", ""), "/login");
});

test("next never leaves the site", () => {
  for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example",
                     "javascript:alert(1)", "/login?next=/x", "%2F%2Fevil.example",
                     "/ok\r\nSet-Cookie: x", "%E0%A4%A"]) {
    assert.equal(safeNext(bad), "/extract", bad);
  }
  assert.equal(safeNext(null), "/extract");
  assert.equal(safeNext("/history"), "/history");
});
