"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { extractApi, exportApi, templatesApi, type JobStatus, type DocumentResult, type ColumnTemplate } from "@/lib/api";
import toast from "react-hot-toast";

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: "badge-green",
    processing: "badge-blue",
    failed: "badge-red",
    pending: "badge-gray",
    cancelled: "badge-gray",
  };
  return <span className={`badge ${map[status] ?? "badge-gray"}`}>{status}</span>;
}

function StatusIcon({ status }: { status: string }) {
  if (status === "completed") return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>;
  if (status === "failed")    return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>;
  if (status === "processing") return <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>;
  return <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="2"><circle cx="12" cy="12" r="10"/></svg>;
}

export default function HistoryPage() {
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  const { data: jobs = [], isLoading } = useQuery<JobStatus[]>({
    queryKey: ["jobs"],
    queryFn: () => extractApi.listJobs({ limit: 50 }),
    refetchInterval: 8000,
  });

  const { data: templates = [] } = useQuery<ColumnTemplate[]>({
    queryKey: ["templates"],
    queryFn: () => templatesApi.list(),
  });

  const { data: results = [] } = useQuery<DocumentResult[]>({
    queryKey: ["job-results", selectedJobId],
    queryFn: () => extractApi.getResults(selectedJobId!),
    enabled: !!selectedJobId,
  });

  const selectedJob = jobs.find(j => j.id === selectedJobId);

  // True when the selected job was run with a template (schema_id is set)
  const jobHasTemplate = Boolean(selectedJob?.schema_id);

  async function handleExport(jobId: number, mode: "template" | "combined" | "perfile") {
    try {
      let blob: Blob;
      let filename: string;
      if (mode === "template") {
        blob = await exportApi.templateExport(jobId);
        filename = `job_${jobId}_results.xlsx`;
      } else if (mode === "combined") {
        blob = await exportApi.combined({ job_id: jobId });
        filename = `job_${jobId}_combined.xlsx`;
      } else {
        blob = await exportApi.perFile({ job_id: jobId });
        filename = `job_${jobId}_perfile.xlsx`;
      }
      exportApi.downloadBlob(blob, filename);
      toast.success("Downloaded");
    } catch { toast.error("Export failed"); }
  }

  function fmt(iso: string | null) {
    if (!iso) return "—";
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  }

  return (
    <AppLayout>
      <style>{`
        .hist-layout { display: grid; grid-template-columns: 340px 1fr; gap: 18px; align-items: start; }
        .job-list { display: flex; flex-direction: column; gap: 5px; }
        .job-card {
          display: flex; align-items: center; gap: 10px;
          padding: 11px 13px; background: var(--surface);
          border: 1px solid var(--border); border-radius: 9px;
          cursor: pointer; transition: border-color 0.12s;
        }
        .job-card:hover { border-color: var(--border2); }
        .job-card.sel { border-color: var(--accent); background: var(--surface2); }
        .job-meta { flex: 1; min-width: 0; }
        .job-id-row { display: flex; align-items: center; gap: 7px; margin-bottom: 2px; }
        .job-id { font-size: 13px; font-weight: 600; color: var(--text1); }
        .job-sub { font-size: 11px; color: var(--text3); }
        .job-counts { display: flex; gap: 8px; margin-top: 3px; }
        .job-count { font-size: 11px; }

        .detail-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
        .detail-title { font-size: 15px; font-weight: 600; color: var(--text1); flex: 1; min-width: 80px; }
        .doc-card { background: var(--surface); border: 1px solid var(--border); border-radius: 9px; padding: 14px; margin-bottom: 8px; }
        .doc-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
        .doc-filename { font-size: 13px; font-weight: 500; color: var(--text1); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .doc-fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 7px; }
        .field-cell { background: var(--surface2); border-radius: 6px; padding: 7px 9px; }
        .field-key { font-size: 10px; color: var(--text4); font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 2px; }
        .field-val { font-size: 12.5px; color: var(--text1); word-break: break-word; font-variant-numeric: tabular-nums; }
        .field-empty { color: var(--text4); font-style: italic; }
      `}</style>

      <div style={{ marginBottom: 22 }}>
        <h1 className="page-title">History</h1>
        <p className="page-sub">All extraction jobs — click to view extracted data</p>
      </div>

      {isLoading ? (
        <p style={{ color: "var(--text3)", fontSize: 13 }}>Loading…</p>
      ) : jobs.length === 0 ? (
        <div className="card" style={{ padding: "48px 32px", textAlign: "center" }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5" style={{ margin: "0 auto 12px", display: "block" }}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          <p style={{ fontWeight: 500, color: "var(--text1)" }}>No jobs yet</p>
          <p style={{ fontSize: 12, color: "var(--text3)", marginTop: 4 }}>Run your first extraction to see history here</p>
        </div>
      ) : (
        <div className="hist-layout">
          {/* Job list */}
          <div>
            <p className="label" style={{ marginBottom: 10 }}>{jobs.length} jobs</p>
            <div className="job-list">
              {jobs.map(job => (
                <div
                  key={job.id}
                  className={`job-card ${selectedJobId === job.id ? "sel" : ""}`}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <StatusIcon status={job.status} />
                  <div className="job-meta">
                    <div className="job-id-row">
                      <span className="job-id">Job #{job.id}</span>
                      <StatusBadge status={job.status} />
                      {/* Small indicator when job was run with a template */}
                      {job.schema_id && (
                        <span style={{ fontSize: 9, padding: "1px 5px", background: "var(--accent-dim)", color: "var(--accent)", borderRadius: 3, fontWeight: 600 }}>TPL</span>
                      )}
                    </div>
                    <div className="job-sub">{fmt(job.created_at)}</div>
                    <div className="job-counts">
                      <span className="job-count" style={{ color: "var(--text3)" }}>{job.total_docs} docs</span>
                      {job.successful > 0 && <span className="job-count" style={{ color: "var(--green)" }}>✓ {job.successful}</span>}
                      {job.failed > 0 && <span className="job-count" style={{ color: "var(--red)" }}>✗ {job.failed}</span>}
                      {job.total_time_sec > 0 && <span className="job-count" style={{ color: "var(--text3)" }}>{job.total_time_sec.toFixed(1)}s</span>}
                    </div>
                  </div>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text4)" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              ))}
            </div>
          </div>

          {/* Job detail */}
          <div>
            {selectedJob ? (
              <>
                <div className="detail-header">
                  <span className="detail-title">Job #{selectedJob.id}</span>
                  <StatusBadge status={selectedJob.status} />
                  {selectedJob.status === "completed" && (
                    <>
                      {/* Template Excel — only shown when job was run with a template */}
                      {jobHasTemplate && (
                        <button
                          className="btn btn-primary btn-sm"
                          title="Download template-layout Excel — one filled block per document"
                          onClick={() => handleExport(selectedJob.id, "template")}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                          Template Excel
                        </button>
                      )}
                      <button className="btn btn-secondary btn-sm" onClick={() => handleExport(selectedJob.id, "combined")}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                        Flat Excel
                      </button>
                      <button className="btn btn-secondary btn-sm" onClick={() => handleExport(selectedJob.id, "perfile")}>Per-file</button>
                    </>
                  )}
                </div>

                {results.length === 0 ? (
                  <div className="card" style={{ padding: 32, textAlign: "center" }}>
                    <svg className="animate-spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="2" style={{ margin: "0 auto 10px", display: "block" }}><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                    <p style={{ fontSize: 13, color: "var(--text3)" }}>Loading results…</p>
                  </div>
                ) : (
                  results.map(doc => {
                    const ext = doc.extracted_data?.extracted_data ?? {};
                    // Filter out internal _label_ keys from display
                    const fields = Object.entries(ext).filter(([k]) => !k.startsWith("_label_"));
                    return (
                      <div key={doc.id} className="doc-card">
                        <div className="doc-header">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                          <span className="doc-filename">{doc.filename}</span>
                          <span style={{ fontSize: 11, color: "var(--text3)" }}>{doc.document_type}</span>
                          {doc.needs_review && <span className="badge badge-amber">Review</span>}
                          {doc.overall_confidence && (
                            <span className={`conf-${doc.overall_confidence}`} style={{ fontSize: 11 }}>
                              {doc.overall_confidence}
                            </span>
                          )}
                        </div>
                        <div className="doc-fields">
                          {fields.map(([k, v]) => {
                            const val = v && typeof v === "object" && "value" in v
                              ? (v as { value: unknown }).value : v;
                            const isEmpty = val === null || val === undefined || val === "";
                            return (
                              <div key={k} className="field-cell">
                                <div className="field-key">{k.replace(/_/g, " ")}</div>
                                <div className={`field-val ${isEmpty ? "field-empty" : ""}`}>
                                  {isEmpty ? "—" : String(val)}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })
                )}
              </>
            ) : (
              <div className="card" style={{ padding: "60px 32px", textAlign: "center" }}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--text4)" strokeWidth="1.5" style={{ margin: "0 auto 12px", display: "block" }}><polyline points="9 18 15 12 9 6"/></svg>
                <p style={{ fontWeight: 500, color: "var(--text2)" }}>Select a job</p>
                <p style={{ fontSize: 12, color: "var(--text3)", marginTop: 4 }}>Click any job to see extracted data</p>
              </div>
            )}
          </div>
        </div>
      )}
    </AppLayout>
  );
}
