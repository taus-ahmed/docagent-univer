// Run: node --test lib/permissions.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { can, mayCancel, mayDelete, seesAdminArea } from "./permissions.ts";

const reviewer = { id: 5, role: "reviewer",
  permissions: ["drive.use", "job.cancel", "job.export", "job.review", "job.upload", "job.view"] };
const tenantAdmin = { id: 1, role: "admin",
  permissions: ["job.cancel", "job.cancel_any", "job.delete", "job.view", "schema.manage",
                "stats.view", "template.create", "user.manage"] };

test("the server's list decides", () => {
  assert.equal(can(reviewer, "job.review"), true);
  assert.equal(can(reviewer, "template.create"), false);
  assert.equal(can(reviewer, "user.manage"), false);
  assert.equal(seesAdminArea(reviewer), false);
  assert.equal(seesAdminArea(tenantAdmin), true);
});

test("a stored session without permissions keeps the old rule", () => {
  assert.equal(seesAdminArea({ role: "admin" }), true);
  assert.equal(seesAdminArea({ role: "client" }), false);
  assert.equal(can({ role: "client" }, "template.create"), true);
  assert.equal(can({ role: "client" }, "job.delete"), false);
  assert.equal(can(null, "job.view"), false);
});

test("cancel: owner or an admin", () => {
  assert.equal(mayCancel(reviewer, { user_id: 5 }), true);
  assert.equal(mayCancel(reviewer, { user_id: 9 }), false);
  assert.equal(mayCancel(tenantAdmin, { user_id: 9 }), true);
  assert.equal(mayCancel(null, { user_id: 9 }), false);
});

test("delete: owner or an admin", () => {
  assert.equal(mayDelete(reviewer, { user_id: 5 }), true);
  assert.equal(mayDelete(reviewer, { user_id: 9 }), false);
  assert.equal(mayDelete(tenantAdmin, { user_id: 9 }), true);
  assert.equal(mayDelete(null, { user_id: 5 }), false);
});
