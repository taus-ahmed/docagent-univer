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
