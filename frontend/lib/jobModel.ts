/** Overnight M2: which model produced a job's values, as the API named it
 *  (document_results.model_used). Distinct, in first-seen order; "" when no
 *  document records one. */
export function jobModels(results: { model_used?: string | null }[]): string {
  const seen: string[] = [];
  for (const r of results) {
    const m = String(r.model_used ?? "").trim();
    if (m && !seen.includes(m)) seen.push(m);
  }
  return seen.join(", ");
}

/** Run Q, Q12: the one line a failed (or partly failed) job shows in the
 *  job list - the job's own stored reason, shortened; never blank for a
 *  failed job. "" for every other status. */
export function failureLine(job: { status?: string; error_message?: string | null }): string {
  if (job.status !== "failed" && job.status !== "partial") return "";
  const m = String(job.error_message ?? "").trim();
  if (!m) return job.status === "failed" ? "Failed — no reason was recorded for this job" : "";
  return m.length > 140 ? m.slice(0, 137) + "…" : m;
}

/** Run Q, UI3: a job's status in short plain words. The raw status stays
 *  available as a tooltip; the failure REASON is `failureLine`. */
export function plainStatus(job: {
  status?: string; needs_review?: number; needs_attention?: number;
  total_docs?: number; blank_forms?: number;
}): string {
  switch (job.status) {
    case "pending":
    case "processing": return "Running";
    case "cancelled": return "Cancelled";
    case "failed": return "Failed";
    case "partial": return "Partly failed";
    case "completed": {
      if ((job.needs_attention ?? 0) > 0 || (job.needs_review ?? 0) > 0) return "Needs review";
      const blank = job.blank_forms ?? 0;
      if (blank > 0 && blank === (job.total_docs ?? 0)) return "Blank form";
      return "Done";
    }
    default: return job.status ?? "";
  }
}
