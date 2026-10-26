// Run: node --test lib/categoryRules.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatRules, parseRules } from "./categoryRules.ts";

test("lines become rules and back", () => {
  const { rules, problems } = parseRules("Fuel: fuel station, diesel\nClient Travel: /^DELTA\\b/, airline");
  assert.deepEqual(problems, []);
  assert.deepEqual(rules[0], { category: "Fuel", keywords: ["fuel station", "diesel"] });
  assert.deepEqual(rules[1].regex, ["^DELTA\\b"]);
  assert.equal(parseRules(formatRules(rules)).rules.length, 2);
});

test("mistakes are named by line in plain words", () => {
  const { problems } = parseRules("no colon here\nEmpty:\nBad: /(unclosed/");
  assert.equal(problems.length, 3);
  assert.match(problems[0], /line 1/);
  assert.match(problems[2], /not valid/);
});
