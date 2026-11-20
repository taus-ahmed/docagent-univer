// Run: node --test lib/reviewRefresh.test.ts
// Overnight E1: after every review action the results are fetched again, so
// an edit saved on the server cannot revert on screen (job 52's Form Type).
import { test } from "node:test";
import assert from "node:assert/strict";
import { refreshAfterReview, reviewRefreshKeys } from "./reviewRefresh.ts";

function recorder() {
  const seen: unknown[][] = [];
  return { seen, invalidateQueries: (f: { queryKey: readonly unknown[] }) => { seen.push([...f.queryKey]); } };
}

test("a review action invalidates the RESULTS query, not only the review query", () => {
  const qc = recorder();
  refreshAfterReview(qc, 52);
  assert.deepEqual(qc.seen, [["review", 52], ["job-results", 52], ["job", 52], ["jobs"]]);
});

test("the results key is the one the Extract and History pages read", () => {
  // both pages load a job's results with useQuery(["job-results", jobId])
  assert.ok(reviewRefreshKeys(7).some(k => k[0] === "job-results" && k[1] === 7));
});

test("each job refreshes only its own queries", () => {
  const qc = recorder();
  refreshAfterReview(qc, 1);
  assert.ok(qc.seen.every(k => k.length === 1 || k[1] === 1));
});
