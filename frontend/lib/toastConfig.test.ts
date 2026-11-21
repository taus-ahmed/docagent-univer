// Run: node --test lib/toastConfig.test.ts
// Run Q, UI2: notifications never cover an action button.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  TOAST_CONTAINER_STYLE, TOAST_DURATION_MS, TOAST_POSITION, inlineConfirmation,
} from "./toastConfig.ts";

test("toasts live bottom-right, away from every header and toolbar button", () => {
  assert.equal(TOAST_POSITION, "bottom-right");
  assert.equal(TOAST_CONTAINER_STYLE.pointerEvents, "none");
});

test("toasts dismiss after about three seconds", () => {
  assert.ok(TOAST_DURATION_MS >= 2500 && TOAST_DURATION_MS <= 3500);
});

test("the app's Toaster uses this configuration, not its own", () => {
  const src = readFileSync(new URL("../app/providers.tsx", import.meta.url), "utf8");
  assert.match(src, /position=\{TOAST_POSITION\}/);
  assert.doesNotMatch(src, /position="top-/);
});

test("a just-marked document reads Reviewed beside the button", () => {
  assert.equal(inlineConfirmation(false, true), "Reviewed");
  assert.equal(inlineConfirmation(true, false), "Reviewed");
  assert.equal(inlineConfirmation(false, false), "");
});
