// The "Additional options" panel's rules (Part A6), pure so they are tested
// without a browser (lib/options.test.ts). What each option does and costs is
// said in plain words; an option that cannot run says why instead of
// silently doing nothing.

export type OptionId = "categorize" | "graphs" | "summary" | "narrative" | "anomaly";

export const OPTION_INFO: Record<OptionId, { label: string; help: string; cost: string }> = {
  categorize: {
    label: "Categorization",
    help: "Gives each line item a category from your template's and firm's rules; only rows no rule fits are asked of the AI, and are marked for review.",
    cost: "Instant for rule matches; at most one AI call per table for the rest.",
  },
  graphs: {
    label: "Charts & graphs",
    help: "Spend by category, by month and largest items, one currency at a time, built from the extracted values; added to the Excel file too.",
    cost: "No AI call. Instant.",
  },
  summary: {
    label: "Summary",
    help: "A short summary built from the extracted values: counts, totals per currency, date range, largest items.",
    cost: "No AI call. Instant.",
  },
  narrative: {
    label: "Written summary (AI)",
    help: "An AI writes the summary as prose from those facts; it is thrown away if it mentions any number, date or name not in the data.",
    cost: "One AI call per document (counts toward your monthly limit); a few seconds.",
  },
  anomaly: {
    label: "Anomaly detection",
    help: "Flags duplicates, outliers, odd dates, gaps in numbering and totals that do not add up, each with the rows and numbers.",
    cost: "No AI call. Instant.",
  },
};

export const OPTION_ORDER: OptionId[] = ["categorize", "graphs", "summary", "narrative", "anomaly"];

/** Whether an option can be chosen now, and if not, why (plain words). */
export function optionState(id: OptionId, selected: OptionId[], ctx: { isDemo?: boolean }) {
  if (ctx.isDemo) return { disabled: true, why: "Not available in the demo." };
  if (id === "narrative" && !selected.includes("summary"))
    return { disabled: true, why: "Turn on Summary first: the written summary is made from it." };
  return { disabled: false, why: "" };
}

/** Toggle one option, keeping prerequisites consistent. */
export function toggle(selected: OptionId[], id: OptionId): OptionId[] {
  const on = selected.includes(id);
  let next = on ? selected.filter(o => o !== id) : [...selected, id];
  if (id === "summary" && on) next = next.filter(o => o !== "narrative");
  return OPTION_ORDER.filter(o => next.includes(o));
}

const KEY = (userId: number | string) => `da_options_${userId}`;

/** The user's remembered choices; [] when none, or storage is unavailable. */
export function loadRemembered(userId: number | string | null | undefined, storage?: Storage | null): OptionId[] {
  if (userId == null) return [];
  try {
    const raw = (storage ?? globalThis.localStorage)?.getItem(KEY(userId));
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? OPTION_ORDER.filter(o => v.includes(o)) : [];
  } catch { return []; }
}

export function saveRemembered(userId: number | string | null | undefined, opts: OptionId[], storage?: Storage | null) {
  if (userId == null) return;
  try { (storage ?? globalThis.localStorage)?.setItem(KEY(userId), JSON.stringify(opts)); } catch { /* private mode */ }
}
