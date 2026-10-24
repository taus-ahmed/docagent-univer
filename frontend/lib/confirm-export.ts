// Before a download: if values still need review, say how many and ask.
// The export is never blocked — the accountant may need the data now — and
// every open value arrives marked in the file (fill, comment, Review status
// column, Legend sheet). This only makes the choice explicit.
import { reviewApi } from "@/lib/api";
import { exportWarning } from "@/lib/review";

export async function confirmExport(jobId: number): Promise<boolean> {
  let warning: string | null;
  try {
    warning = exportWarning((await reviewApi.job(jobId)).summary);
  } catch {
    warning = "The review status could not be checked. Values that need review " +
              "are still marked in the file. Export anyway?";
  }
  return warning === null || window.confirm(warning);
}
