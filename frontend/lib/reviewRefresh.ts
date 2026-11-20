/**
 * Overnight E1 — after EVERY review action, the screen re-reads what the
 * server stored.
 *
 * The API persisted a corrected Form Type (job 52), yet the value on screen
 * reverted: ReviewPanel saved the correction without touching the results it
 * was given, and ResultsGrid's refresh invalidated only the review query, so
 * the grid and the dialog kept the copy loaded before the edit. Status and
 * added rows went stale the same way. One list of queries, invalidated after
 * every action — accept, correct, mark empty, edit, add row, settle a reason,
 * mark the document reviewed.
 */

export interface InvalidatingClient {
  invalidateQueries(filters: { queryKey: readonly unknown[] }): unknown;
}

/** The queries a review action can make stale, for one job. */
export function reviewRefreshKeys(jobId: number): (readonly unknown[])[] {
  return [
    ["review", jobId],          // per-value statuses, reasons, document state
    ["job-results", jobId],     // the stored extracted_data (values, rows)
    ["job", jobId],             // the job's counts (needs review, etc.)
    ["jobs"],                   // the history list's badges
  ];
}

/** Invalidate every query a review action can make stale. */
export function refreshAfterReview(qc: InvalidatingClient, jobId: number): void {
  for (const queryKey of reviewRefreshKeys(jobId)) {
    qc.invalidateQueries({ queryKey });
  }
}
