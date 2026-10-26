// Chart data from the server (GET /api/jobs/{id}/charts, engine/charts.py):
// exact sums, one currency at a time. Here only the conversion to bars —
// nothing is parsed or added in the browser (Part A5).

export type ChartsResponse = {
  currencies: Record<string, {
    by_category: [string, string][];
    by_month: [string, string][];
    top_items: [string, string][];
    distribution: [string, number][];
    count: number;
  }>;
  values: number;
  left_out_ambiguous: number;
  message: string | null;
  needs_review: number;
};

const PALETTE = ["#4f46e5", "#059669", "#d97706", "#dc2626", "#0891b2", "#7c3aed", "#65a30d", "#db2777"];

export function bars(series: [string, string | number][], limit = 8) {
  return (series || []).slice(0, limit).map(([label, v], i) => ({
    label, value: Number(v), color: PALETTE[i % PALETTE.length],
  }));
}

/** The banner every chart carries, or null when nothing needs review. */
export function reviewBanner(c: Pick<ChartsResponse, "needs_review">): string | null {
  if (!c.needs_review) return null;
  return `Includes ${c.needs_review} value${c.needs_review === 1 ? "" : "s"} that still need${c.needs_review === 1 ? "s" : ""} review.`;
}

/** Why there is no chart, in plain words, or null when there is something to show. */
export function emptyReason(c: ChartsResponse | undefined): string | null {
  if (!c) return "Loading charts…";
  if (!Object.keys(c.currencies || {}).length || c.values < 2) return c.message || "Not enough amounts to chart.";
  return null;
}
