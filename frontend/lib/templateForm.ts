// Template editor form rules (Part A7): errors shown NEXT TO the field they
// belong to, in plain words, and the unsaved-changes guard. Pure, so they are
// tested without a browser (lib/templateForm.test.ts).

/** Identifier kinds the engine has a plug-in for (engine/identifiers/). */
export const ID_TYPES = ["aba", "bic", "ein", "gstin", "iban", "ifsc", "pan",
  "swift", "trn", "uk_sort_code", "vat"] as const;

export type FieldError = { field: "name" | "docType" | "grid" | "locale"; message: string };

const LOCALE = /^[a-z]{2,3}(-[A-Za-z]{2,4})?$/;

export function validateTemplate(input: {
  name: string;
  docType: string;
  customDocType?: string;
  cells?: Record<string, { value?: string; id_type?: string } | undefined>;
  locale?: string | null;
  existingNames?: string[];
  ownId?: number | null;
}): FieldError[] {
  const out: FieldError[] = [];
  const name = (input.name || "").trim();
  if (!name) out.push({ field: "name", message: "Give the template a name." });
  else if (name.length > 120) out.push({ field: "name", message: "Keep the name under 120 characters." });
  else if ((input.existingNames || []).some(n => n.trim().toLowerCase() === name.toLowerCase()))
    out.push({ field: "name", message: "Another template already has this name." });
  if (input.docType === "other") {
    const c = (input.customDocType || "").trim();
    if (c && !/^[a-z][a-z0-9_]{1,40}$/.test(c))
      out.push({ field: "docType", message: "Use lower-case letters, digits and _ (e.g. pay_order)." });
  }
  const cells = Object.entries(input.cells || {});
  if (!cells.some(([, c]) => (c?.value || "").trim()))
    out.push({ field: "grid", message: "Type at least one label in the grid." });
  for (const [k, c] of cells) {
    const t = c?.id_type;
    if (t && !(ID_TYPES as readonly string[]).includes(t)) {
      const [r, col] = k.split(",").map(Number);
      out.push({ field: "grid", message:
        `Cell ${String.fromCharCode(65 + col)}${r + 1}: "${t}" is not a known identifier type (${ID_TYPES.join(", ")}).` });
    }
  }
  if (input.locale && !LOCALE.test(input.locale))
    out.push({ field: "locale", message: `"${input.locale}" is not a locale like en-US, en-IN or de-DE.` });
  return out;
}

/** What a grid holds that a user would lose: non-empty values, styles,
 *  merges and declared regions — never bookkeeping such as empty entries. */
export function gridSignature(grid: any): string {
  const cells = Object.entries((grid && grid.cells) || {})
    .filter(([, c]: [string, any]) => (c?.value ?? "") !== "" || Object.keys(c?.style || {}).length || c?.id_type)
    .map(([k, c]: [string, any]) => [k, c?.value ?? "", c?.style ?? {}, c?.id_type ?? ""])
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  return JSON.stringify({ cells, merges: (grid && grid.merges) || {}, regions: (grid && grid.regions) || [] });
}

/** The text of the browser's leave-page warning, or null when nothing is unsaved. */
export function leaveWarning(dirty: boolean): string | null {
  return dirty ? "You have unsaved changes to this template. Leave without saving?" : null;
}
