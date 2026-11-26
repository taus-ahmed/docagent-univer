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

export function jobTemplateId(job?: HasSchemaId | null): number | null | undefined {
  if (job?.schema_id === null) return null;
  const id = Number(job?.schema_id);
  return Number.isSafeInteger(id) && id > 0 ? id : undefined;
}

/** The template a job was extracted with, if present in this list. */
export function templateOfJob<T extends HasId>(job: HasSchemaId | null | undefined,
                                               templates: readonly T[]): T | null {
  const id = jobTemplateId(job);
  return templates.find(t => t.id === id) ?? null;
}

export function templateUsedLabel(job: HasSchemaId | null | undefined, template: { name: string } | null, loading = false): string {
  const id = jobTemplateId(job);
  if (id === null) return "No template, layout inferred from the document";
  if (id === undefined) return "Template information unavailable";
  return template?.name ?? (loading ? "Loading template…" : `Template #${id} (name unavailable)`);
}
