// Review screen logic — pure functions, no React, no network, so they can be
// tested with `node --test` (see lib/review.test.ts).
//
// The classification itself is done ONCE, on the server (backend/app/core/
// review.py), and arrives with every value as `status` and `resolved`. This
// module only arranges it for display: rows, columns, filters, counts and the
// badge each status gets. It never decides whether a value needs review.

export type ReviewStatus =
  | "verified" | "grounded" | "unverified" | "low" | "edited"
  | "empty_flagged" | "empty" | "unknown";

export interface ReviewValue {
  kind: "field" | "cell";
  ref: string | null;
  label: string;
  value: unknown;
  level: string | null;
  page: number | null;
  source: string | null;
  table?: string;
  row?: number;
  column?: string;
  status: ReviewStatus;
  reasons: string[];
  review_required: boolean;
  reviewed: boolean;
  resolved: boolean;
}

export interface ReviewSummary {
  values: number;
  needs_review: number;
  low: number;
  unverified: number;
  empty_flagged: number;
  documents?: number;
  documents_needing_review?: number;
}

export interface ReviewDoc {
  doc_id: number;
  filename: string;
  original_filename: string;
  document_index: number | null;
  document_count: number | null;
  document_type: string | null;
  pages: number[];
  needs_review: boolean;
  document_reviewed: boolean;
  failed: boolean;
  error: string;
  values: ReviewValue[];
  summary: ReviewSummary;
}

export interface JobReview {
  job_id: number;
  summary: ReviewSummary;
  documents: ReviewDoc[];
}

export interface ReasonText { label: string; tooltip: string }
export type ReasonMap = Record<string, ReasonText>;

export type Filter = "all" | "needs_review" | "low" | "unverified";

export const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "needs_review", label: "Needs review" },
  { id: "low", label: "Low only" },
  { id: "unverified", label: "Unverified only" },
];

/** Badge text and colours. Every status has a WORD as well as a colour, so a
 *  colour-blind reader and a black-and-white print lose nothing. Colours are
 *  dark text on a light tint: WCAG AA contrast (≥ 4.5:1) for 11px text. */
export const BADGES: Record<ReviewStatus, { text: string; fg: string; bg: string }> = {
  verified:      { text: "Verified",       fg: "#065f46", bg: "#d1fae5" },
  grounded:      { text: "Grounded",       fg: "#1e3a8a", bg: "#dbeafe" },
  unverified:    { text: "Unverified",     fg: "#78350f", bg: "#fef3c7" },
  low:           { text: "Low",            fg: "#7f1d1d", bg: "#fee2e2" },
  edited:        { text: "Edited",         fg: "#4c1d95", bg: "#ede9fe" },
  empty_flagged: { text: "Empty, flagged", fg: "#374151", bg: "#e5e7eb" },
  empty:         { text: "Empty",          fg: "#4b5563", bg: "#f3f4f6" },
  unknown:       { text: "Unknown",        fg: "#78350f", bg: "#fef3c7" },
};

/** The badge for a value: a confident level that still owes a look says so. */
export function badgeFor(v: Pick<ReviewValue, "status" | "resolved" | "reviewed">) {
  const b = BADGES[v.status] ?? BADGES.unknown;
  if (!v.resolved && (v.status === "verified" || v.status === "grounded")) {
    return { ...b, text: `${b.text} · review`, fg: "#78350f", bg: "#fef3c7" };
  }
  if (v.reviewed && v.status !== "edited") {
    return { ...b, text: `${b.text} · reviewed` };
  }
  return b;
}

/** A reason code as text; an unknown code is shown, never hidden. */
export function reasonText(code: string, map: ReasonMap | undefined): ReasonText {
  const hit = map?.[code];
  if (hit) return hit;
  // A declared rule's code carries its name: `rule_failed:lines_sum`
  // (backend/app/core/review.py::reason_text does the same).
  const i = code.indexOf(":");
  const base = i > 0 ? map?.[code.slice(0, i)] : undefined;
  if (base) return { label: `${base.label} (${code.slice(i + 1)})`, tooltip: base.tooltip };
  return { label: `Needs review (${code})`,
           tooltip: `Reason code '${code}' has no description yet. The value still needs review.` };
}

/** "statement.pdf [2 of 3] · p.1–2" — the record as the user knows it. */
export function recordLabel(d: Pick<ReviewDoc, "filename" | "pages">): string {
  const pages = d.pages ?? [];
  if (!pages.length) return d.filename;
  const p = pages.length === 1 ? `p.${pages[0]}` : `p.${pages[0]}–${pages[pages.length - 1]}`;
  return `${d.filename} · ${p}`;
}

/** The field columns, in first-seen order across documents. */
export function fieldColumns(docs: ReviewDoc[]): string[] {
  const seen: string[] = [];
  for (const d of docs) {
    for (const v of d.values) {
      if (v.kind === "field" && !seen.includes(v.label)) seen.push(v.label);
    }
  }
  return seen;
}

export function fieldsByLabel(d: ReviewDoc): Record<string, ReviewValue> {
  const out: Record<string, ReviewValue> = {};
  for (const v of d.values) if (v.kind === "field" && !(v.label in out)) out[v.label] = v;
  return out;
}

/** Does a document belong under a filter. A failed document always shows
 *  under "needs review": nothing came out of it and someone has to look. */
export function matches(d: ReviewDoc, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "needs_review") return d.summary.needs_review > 0 || (d.failed && !d.document_reviewed);
  if (f === "low") return d.values.some(v => !v.resolved && v.status === "low");
  return d.values.some(v => !v.resolved && v.status === "unverified");
}

export function filterDocs(docs: ReviewDoc[], f: Filter): ReviewDoc[] {
  return docs.filter(d => matches(d, f));
}

/** Indexes (into `values`) of the values still owed a look, in order. */
export function openIndexes(values: ReviewValue[]): number[] {
  return values.map((v, i) => (v.resolved ? -1 : i)).filter(i => i >= 0);
}

/** The next / previous open value from `from`, wrapping; -1 when none. */
export function stepOpen(values: ReviewValue[], from: number, dir: 1 | -1): number {
  const open = openIndexes(values);
  if (!open.length) return -1;
  if (dir === 1) return open.find(i => i > from) ?? open[0];
  for (let k = open.length - 1; k >= 0; k--) if (open[k] < from) return open[k];
  return open[open.length - 1];
}

/** Box (points, frame top-left) → CSS percentages of the shown image. */
export function boxToPercent(box: number[], widthPt: number, heightPt: number) {
  const [x0, top, x1, bottom] = box;
  return {
    left: `${(100 * x0) / widthPt}%`, top: `${(100 * top) / heightPt}%`,
    width: `${(100 * (x1 - x0)) / widthPt}%`, height: `${(100 * (bottom - top)) / heightPt}%`,
  };
}

/** The sentence the export dialog shows before a download with open values. */
export function exportWarning(s: ReviewSummary | undefined): string | null {
  if (!s || s.needs_review === 0) return null;
  const n = s.needs_review;
  return `${n} value${n === 1 ? "" : "s"} still need${n === 1 ? "s" : ""} review ` +
         `(${s.low} low, ${s.unverified} unverified, ${s.empty_flagged} empty and flagged). ` +
         `They will be exported with a coloured fill, a comment saying why, and a ` +
         `"Review status" column. Export anyway?`;
}
