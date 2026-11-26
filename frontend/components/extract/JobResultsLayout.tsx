"use client";

import { useState, type ReactNode } from "react";
import { Download } from "lucide-react";
import toast from "react-hot-toast";
import { exportApi, type ColumnTemplate, type JobStatus } from "@/lib/api";
import { confirmExport } from "@/lib/confirm-export";
import { plainStatus } from "@/lib/jobModel";
import { templateUsedLabel } from "@/lib/jobTemplate";
import NewExtractionButton from "./NewExtractionButton";

type DownloadKind = "organized" | "regular" | "audit" | "zip";

interface Props {
  job: JobStatus;
  template: ColumnTemplate | null;
  templateLoading: boolean;
  documentCount: number;
  canDownload?: boolean;
  onNew?: () => void;
  children: ReactNode;
}

export default function JobResultsLayout({ job, template, templateLoading, documentCount, canDownload = true, onNew, children }: Props) {
  const [busy, setBusy] = useState<DownloadKind | null>(null);
  const [organizedUnavailable, setOrganizedUnavailable] = useState<string | null>(null);
  const partial = job.status === "partial";
  const status = plainStatus(job);

  async function download(kind: DownloadKind) {
    setBusy(kind);
    if (kind === "organized") setOrganizedUnavailable(null);
    try {
      if (!await confirmExport(job.id)) return;
      let blob: Blob;
      let suffix: string;
      if (kind === "organized") {
        blob = await exportApi.organizedExport(job.id);
        suffix = "organized.xlsx";
      } else if (kind === "zip") {
        blob = await exportApi.zipExport(job.id, false);
        suffix = "documents.zip";
      } else {
        blob = await exportApi.templateExport(job.id, kind === "audit");
        suffix = kind === "audit" ? "results_audit.xlsx" : "results.xlsx";
      }
      exportApi.downloadBlob(blob, `job_${job.id}_${suffix}`);
      toast.success("Downloaded");
    } catch (e) {
      if (kind === "organized") setOrganizedUnavailable(e instanceof Error && e.message ? e.message : "Organized layout isn't available. Use Download Excel.");
      else toast.error("Export failed");
    } finally {
      setBusy(null);
    }
  }

  function downloadButton(kind: DownloadKind, label: string) {
    return <button type="button" className={`btn btn-full ${kind === "regular" ? "btn-primary" : "btn-secondary"}`}
      disabled={busy !== null} onClick={() => download(kind)}>
      <Download size={15} aria-hidden="true" /> {busy === kind ? "Preparing download…" : label}
    </button>;
  }

  return (
    <div className="job-results-layout">
      <aside className="job-results-sidebar" aria-label="Job details and downloads">
        <section className="card job-result-info">
          <h2 className="label">Template used</h2>
          <p>{templateUsedLabel(job, template, templateLoading)}</p>
        </section>
        <section className="card job-result-info">
          <h2 className="label">Status</h2>
          <p>{job.status === "completed" ? `Extraction complete · ${status}` : status}</p>
          <p className="job-result-counts">
            {job.successful} of {job.total_docs} {job.total_docs === 1 ? "document" : "documents"} extracted
            {partial && ` · ${job.failed} failed`}
            {` · ${job.total_time_sec.toFixed(1)}s`}
          </p>
          {job.pages_total != null && <p className="job-result-counts">{job.pages_processed} of {job.pages_total} pages processed</p>}
          {(job.needs_attention ?? 0) > 0 && <p className="job-result-counts">{job.needs_attention} need attention</p>}
        </section>
        {canDownload && (
          <>
            <div className="card job-result-action">
              {downloadButton("organized", "Download Organized")}
              {organizedUnavailable && <p className="job-result-error" role="alert">
                {organizedUnavailable}
              </p>}
            </div>
            <div className="card job-result-action">{downloadButton("regular", "Download Excel")}</div>
            <div className="card job-result-action"><NewExtractionButton onNew={onNew} /></div>
            <div className="card job-result-action">{downloadButton("audit", "Download with audit columns")}</div>
            {Math.max(job.total_docs, documentCount) > 1 && (
              <div className="card job-result-action">{downloadButton("zip", "Download ZIP")}</div>
            )}
          </>
        )}
      </aside>
      <div className="job-results-content">{children}</div>
    </div>
  );
}
