// Run G, G5 — the review actions as data: what each button sends, what a
// click on the results grid does, and how a history event reads. Pure (no
// React, no network) so `node --test lib/reviewActions.test.ts` covers every
// action the review dialog offers. The server (backend/app/api/routes/
// review.py) owns the rules; this only builds the requests it documents.

export type ValueDisposition = "accepted_as_is" | "corrected" | "confirmed_empty";

/** The address of one reviewable value. */
export interface ValueAddress {
  kind: "field" | "cell" | "category";
  ref: string | null;
  table?: string;
  row?: number;
  row_id?: string | null;
  column?: string;
}

export type ValueEntry =
  | { ref: string; disposition: ValueDisposition; value?: string }
  | { table: string; row: number; row_id?: string; column: string;
      disposition: ValueDisposition; value?: string };

export class NotReviewable extends Error {}

/** One `values[]` entry for `POST .../review`. A table value always names
 *  its column — accepting one cell never accepts its row — and a correction
 *  always carries the corrected text. */
export function valueEntry(v: ValueAddress, disposition: ValueDisposition,
                           value?: string): ValueEntry {
  if (disposition === "corrected" && value === undefined) {
    throw new NotReviewable("A correction needs the corrected value");
  }
  const extra = disposition === "corrected" ? { value } : {};
  if (v.kind === "field" && v.ref) {
    return { ref: String(v.ref), disposition, ...extra };
  }
  if (v.kind === "cell" && v.table != null && v.row != null && v.column) {
    return { table: String(v.table), row: Number(v.row),
             ...(v.row_id ? { row_id: String(v.row_id) } : {}),
             column: String(v.column), disposition, ...extra };
  }
  throw new NotReviewable("This value cannot be reviewed here");
}

/** The three actions a flagged value offers, in button order. */
export const FLAGGED_ACTIONS: { id: ValueDisposition; label: string; key: string;
                                hint: string }[] = [
  { id: "accepted_as_is", label: "Accept as is", key: "a",
    hint: "The value is right as extracted." },
  { id: "corrected", label: "Correct", key: "c",
    hint: "Type the right value; it is saved and accepted in one step." },
  { id: "confirmed_empty", label: "Mark empty", key: "m",
    hint: "The document has no value here; the slot is cleared and its flag set aside." },
];

/** A Mark-empty only makes sense on a field slot or a cell: a category is
 *  not a printed value. */
export function actionsFor(v: ValueAddress & { resolved: boolean }) {
  if (v.resolved || v.kind === "category") return [];
  return FLAGGED_ACTIONS;
}

export function reviewBody(entries: ValueEntry[]) {
  return { values: entries };
}

/** The toast after an action. */
export function actionDone(d: ValueDisposition): string {
  return { accepted_as_is: "Accepted as is", corrected: "Corrected and accepted",
           confirmed_empty: "Marked empty" }[d];
}

// ── add row ─────────────────────────────────────────────────────────────────

export interface TableSpec { name: string; columns: string[] }

/** The tables of a stored result, with their column keys, from its slot
 *  map (the same columns the server accepts). */
export function tablesOf(extracted: any): TableSpec[] {
  const out: TableSpec[] = [];
  for (const t of extracted?.slot_map?.tables ?? []) {
    if (!t || !t.name) continue;
    const cols = (t.columns ?? []).map((c: any) => String(c?.key ?? c?.header ?? ""))
      .filter((c: string) => c);
    if (cols.length) out.push({ name: String(t.name), columns: cols });
  }
  return out;
}

/** The body for `POST .../rows/{table}`: only typed, non-blank values of
 *  the table's own columns. Null when nothing was typed (the server would
 *  refuse it too). */
export function addRowBody(spec: TableSpec, typed: Record<string, string>,
                           attentionId?: string | null) {
  const values: Record<string, string> = {};
  for (const c of spec.columns) {
    const v = (typed[c] ?? "").trim();
    if (v) values[c] = v;
  }
  if (!Object.keys(values).length) return null;
  return attentionId ? { values, attention_id: attentionId } : { values };
}

// ── results grid clicks ─────────────────────────────────────────────────────

export type GridGesture = "click" | "double";
export type GridOutcome = "select" | "edit" | "review" | "rows" | "none";

/** What a gesture on a grid cell does. A single click only SELECTS — it used
 *  to open the review dialog, which swallowed the double-click that edits.
 *  A double-click edits a scalar value cell inline; the Review button opens
 *  the dialog; the Rows count toggles the line items. */
export function gridAction(colId: string | null | undefined, gesture: GridGesture): GridOutcome {
  const col = colId ?? "";
  if (col === "_review") return gesture === "click" ? "review" : "none";
  if (col === "_has_rows") return gesture === "click" ? "rows" : "none";
  if (col.startsWith("_") || !col) return gesture === "click" ? "select" : "none";
  return gesture === "double" ? "edit" : "select";
}

// ── history ─────────────────────────────────────────────────────────────────

export interface HistoryEvent {
  kind: string; by?: string; at?: string; ref?: string; table?: string;
  row?: number; row_id?: string; column?: string; old?: unknown; new?: unknown;
  value?: unknown; disposition?: string; values?: Record<string, string>;
  text?: string; note?: string; reason?: string;
}

function show(v: unknown): string {
  const s = v === null || v === undefined ? "" : String(v);
  return s === "" ? "(empty)" : `"${s}"`;
}

/** One plain line per event: who, when, what, old → new. */
export function historyLine(e: HistoryEvent): string {
  const who = `${e.by ?? "someone"}, ${e.at ?? "time not recorded"}`;
  const where = e.kind === "field" || (e.kind === "review" && e.ref) ? `${e.ref}`
    : e.table ? `${e.table} row ${(e.row ?? 0) + 1}${e.column ? `: ${e.column}` : ""}`
    : "";
  const verb: Record<string, string> = {
    accepted_as_is: "accepted as is", corrected: "corrected",
    confirmed_empty: "marked empty", document_reviewed: "marked the document reviewed",
    confirmed_absent: "confirmed absent", entered_manually: "entered by hand",
  };
  if (e.kind === "add_row") {
    const vals = Object.entries(e.values ?? {}).map(([k, v]) => `${k}: ${v}`).join(" · ");
    return `${who} — added a row to ${e.table}: ${vals}`;
  }
  if (e.kind === "attention") {
    return `${who} — ${verb[e.disposition ?? ""] ?? e.disposition}: ${e.text ?? ""}`;
  }
  if (e.kind === "document") return `${who} — ${verb.document_reviewed}`;
  if (e.disposition === "accepted_as_is") return `${who} — ${where} accepted as is (${show(e.value ?? e.old)})`;
  const act = e.disposition ? verb[e.disposition] ?? e.disposition : "edited";
  return `${who} — ${where} ${act}: ${show(e.old)} → ${show(e.new)}`;
}
