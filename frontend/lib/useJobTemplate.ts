import { useQuery } from "@tanstack/react-query";
import { templatesApi, type ColumnTemplate } from "./api";
import { jobTemplateId, templateOfJob, type HasSchemaId } from "./jobTemplate";

export function useJobTemplate(job?: HasSchemaId, templates: readonly ColumnTemplate[] = []) {
  const listed = templateOfJob(job, templates);
  const id = jobTemplateId(job);
  const detail = useQuery({
    queryKey: ["template", id],
    queryFn: () => templatesApi.get(id!),
    enabled: id != null && !listed,
    retry: false,
  });
  return { template: listed ?? detail.data ?? null, templateLoading: detail.isLoading };
}
