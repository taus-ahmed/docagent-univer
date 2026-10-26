// Run: node --test lib/options.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { OPTION_INFO, OPTION_ORDER, loadRemembered, optionState, saveRemembered, toggle } from "./options.ts";

test("every option says what it does and what it costs", () => {
  for (const id of OPTION_ORDER) {
    assert.ok(OPTION_INFO[id].help.length > 20 && OPTION_INFO[id].cost.length > 5, id);
  }
});

test("the written summary needs the summary, and says so", () => {
  assert.equal(optionState("narrative", [], {}).disabled, true);
  assert.match(optionState("narrative", [], {}).why, /Summary first/);
  assert.equal(optionState("narrative", ["summary"], {}).disabled, false);
  assert.deepEqual(toggle(["summary", "narrative"], "summary"), []);
});

test("the demo disables every option with a reason", () => {
  assert.equal(optionState("graphs", [], { isDemo: true }).disabled, true);
});

test("choices are remembered per user and survive broken storage", () => {
  const mem = new Map<string, string>();
  const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => { mem.set(k, v); } } as any;
  saveRemembered(7, ["graphs", "anomaly"], store);
  assert.deepEqual(loadRemembered(7, store), ["graphs", "anomaly"]);
  assert.deepEqual(loadRemembered(8, store), []);
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } } as any;
  assert.deepEqual(loadRemembered(7, broken), []);
  saveRemembered(7, ["graphs"], broken);   // does not throw
});
