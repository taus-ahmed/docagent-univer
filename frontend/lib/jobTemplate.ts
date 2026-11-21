// Run Q, UI1: a finished job's results are shown with the template the job
// RAN with, never with whatever the template picker currently holds.
//
// Before: the extract page passed `selectedTemplate` (the picker) to the
// results grid, and the grid takes its columns from that template. Picking
// another template after a result was shown re-laid the grid with the new
// template's columns, so values the job extracted vanished from view and
// columns it never extracted appeared blank. The job itself was unchanged
// and the download was right; what the screen showed was not.

export interface HasSchemaId { schema_id?: string | number | null }
export interface HasId { id: number }

/** The template a job was extracted with, or null (no template / unknown). */
export function templateOfJob<T extends HasId>(job: HasSchemaId | null | undefined,
                                               templates: readonly T[]): T | null {
  const sid = job?.schema_id;
  if (sid === null || sid === undefined || sid === "") return null;
  const n = Number(sid);
  if (!Number.isFinite(n)) return null;
  return templates.find(t => t.id === n) ?? null;
}

/** The body of a re-run request: a template id, or null for "no template". */
export function rerunBody(templateId: number | null): { template_id: number | null } {
  return { template_id: templateId ?? null };
}
