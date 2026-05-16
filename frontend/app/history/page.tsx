"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
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

// ── Table rows display ────────────────────────────────────────────────────────

function TableRowsSection({ rows }: { rows: Record<string, any>[] }) {
  const [open, setOpen] = useState(false);
  if (!rows.length) return null;

  // Filter internal keys
  const displayRows = rows.map(r => {
    const clean: Record<string, any> = {};
    for (const [k, v] of Object.entries(r)) {
      if (!k.startsWith("_")) clean[k] = v;
    }
    return clean;
  });

  const cols = displayRows.length > 0 ? Object.keys(displayRows[0]) : [];

  return (
    <div style={{ marginTop: 12, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
      <button
        onClick={() => setOpen(p => !p)}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "none", border: "none", cursor: "pointer",
          fontSize: 12, fontWeight: 600, color: "var(--accent)", padding: 0,
        }}
      >
        <svg
          width="12" height="12" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" strokeWidth="2"
          style={{ transform: open ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.15s" }}
        >
          <polyline points="9 18 15 12 9 6"/>
        </svg>
        {rows.length} line item{rows.length !== 1 ? "s" : ""}
        <span style={{ fontSize: 10, color: "var(--text3)", fontWeight: 400 }}>
          ({cols.slice(0,3).join(", ")}{cols.length > 3 ? "…" : ""})
        </span>
      </button>

      {open && (
        <div style={{ marginTop: 8, overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: 11, width: "100%", minWidth: 400 }}>
            <thead>
              <tr>
                {cols.map(c => (
                  <th key={c} style={{
                    padding: "5px 10px", textAlign: "left",
                    borderBottom: "2px solid var(--border)",
                    color: "var(--text3)", fontWeight: 700,
                    whiteSpace: "nowrap", fontSize: 10,
                    textTransform: "uppercase", letterSpacing: "0.04em",
                    background: "var(--surface2)",
                  }}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayRows.map((row, i) => (
                <tr key={i} style={{
                  background: i % 2 === 0 ? "transparent" : "var(--surface2)",
                }}>
                  {cols.map(c => (
                    <td key={c} style={{
                      padding: "5px 10px",
                      borderBottom: "1px solid var(--border)",
                      color: "var(--text1)",
                      whiteSpace: "nowrap",
                      fontVariantNumeric: "tabular-nums",
                    }}>
                      {String(row[c] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Error detail panel ────────────────────────────────────────────────────────

function ErrorPanel({ doc }: { doc: DocumentResult }) {
  const errorMsg = (doc as any).error_message || (doc as any).error || null;
  const confidence = doc.overall_confidence;
  const flagged = doc.extracted_data?.validation?.flagged_fields ?? [];

  return (
    <div style={{
      marginTop: 10, padding: "12px 14px",
      background: "var(--red-dim, #fee2e218)",
      border: "1px solid var(--red, #ef4444)44",
      borderRadius: 8,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--red,#ef4444)" strokeWidth="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
          <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
        </svg>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--red,#ef4444)" }}>
          Extraction issue
        </span>
      </div>
      {errorMsg && (
        <p style={{ fontSize: 11, color: "var(--text2)", marginBottom: 6, fontFamily: "monospace", wordBreak: "break-all" }}>
          {errorMsg}
        </p>
      )}
      {flagged.length > 0 && (
        <div>
          <p style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", marginBottom: 4 }}>
            {flagged.length} low-confidence field{flagged.length !== 1 ? "s" : ""}:
          </p>
          {flagged.map((f: any, i: number) => (
            <div key={i} style={{
              display: "flex", gap: 6, fontSize: 11,
              padding: "3px 0", color: "var(--text2)",
            }}>
              <span style={{ fontWeight: 600, color: "var(--amber,#f59e0b)", flexShrink: 0 }}>{f.ref}</span>
              <span style={{ color: "var(--text1)" }}>"{f.value}"</span>
              <span style={{ color: "var(--text3)" }}>— {f.reason}</span>
            </div>
          ))}
        </div>
      )}
      {!errorMsg && flagged.length === 0 && (
        <p style={{ fontSize: 11, color: "var(--text3)" }}>
          Document was processed but some fields may be missing or incorrect.
          Download the Excel to review.
        </p>
      )}
    </div>
  );
}

// ── Document card ─────────────────────────────────────────────────────────────

function DocCard({ doc }: { doc: DocumentResult }) {
  const ext    = doc.extracted_data?.extracted_data ?? {};
  const rows   = doc.extracted_data?.table_rows ?? [];
  const fields = Object.entries(ext).filter(([k]) => !k.startsWith("_label_") && !k.startsWith("_"));
  const hasIssue = doc.needs_review || doc.overall_confidence === "low" || (doc as any).status === "failed";

  return (
    <div style={{
      background: "var(--surface)",
      border: `1px solid ${hasIssue ? "var(--amber,#f59e0b)44" : "var(--border)"}`,
      borderRadius: 9, padding: 14, marginBottom: 8,
    }}>
      {/* Doc header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: fields.length > 0 ? 10 : 0 }}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text1)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {doc.filename}
        </span>
        {doc.document_type && (
          <span style={{ fontSize: 11, color: "var(--text3)", flexShrink: 0 }}>{doc.document_type}</span>
        )}
        {doc.needs_review && <span className="badge badge-amber">Review</span>}
        {doc.overall_confidence && (
          <span style={{ fontSize: 11, color: doc.overall_confidence === "high" ? "var(--green)" : doc.overall_confidence === "low" ? "var(--red)" : "var(--amber)", flexShrink: 0 }}>
            {doc.overall_confidence}
          </span>
        )}
        {(doc as any).tokens_used && (
          <span style={{ fontSize: 10, color: "var(--text4)", flexShrink: 0 }}>
            {(doc as any).tokens_used.toLocaleString()} tokens
          </span>
        )}
      </div>

      {/* Failed — no fields extracted */}
      {fields.length === 0 && rows.length === 0 && (
        <div style={{ padding: "10px 0" }}>
          <ErrorPanel doc={doc} />
        </div>
      )}

      {/* Form fields grid */}
      {fields.length > 0 && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: 7,
        }}>
          {fields.map(([k, v]) => {
            const val = v && typeof v === "object" && "value" in v
              ? (v as { value: unknown }).value : v;
            const conf = v && typeof v === "object" && "confidence" in v
              ? (v as any).confidence : null;
            const isEmpty = val === null || val === undefined || val === "";
            return (
              <div key={k} style={{
                background: "var(--surface2)", borderRadius: 6, padding: "7px 9px",
                borderLeft: conf === "low" ? "3px solid var(--amber,#f59e0b)" : "3px solid transparent",
              }}>
                <div style={{ fontSize: 10, color: "var(--text4)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", marginBottom: 2 }}>
                  {k.replace(/_/g, " ")}
                </div>
                <div style={{ fontSize: 12.5, color: isEmpty ? "var(--text4)" : "var(--text1)", fontStyle: isEmpty ? "italic" : "normal", fontVariantNumeric: "tabular-nums", wordBreak: "break-word" }}>
                  {isEmpty ? "—" : String(val)}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Table rows — collapsible */}
      <TableRowsSection rows={rows} />

      {/* Error panel for review items */}
      {hasIssue && fields.length > 0 && <ErrorPanel doc={doc} />}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  const { data: jobs = [], isLoading } = useQuery<JobStatus[]>({
    queryKey: ["jobs"],
    queryFn:  () => extractApi.listJobs({ limit: 50 }),
    refetchInterval: 8000,
  });

  const { data: results = [], isLoading: resultsLoading } = useQuery<DocumentResult[]>({
    queryKey: ["job-results", selectedJobId],
    queryFn:  () => extractApi.getResults(selectedJobId!),
    enabled:  !!selectedJobId,
  });

  const selectedJob    = jobs.find(j => j.id === selectedJobId);
  const jobHasTemplate = Boolean(selectedJob?.schema_id);

  async function handleExport(jobId: number, mode: "template" | "combined" | "perfile") {
    try {
      let blob: Blob; let filename: string;
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

  // Summary stats for selected job
  const totalRows   = results.reduce((s, d) => s + (d.extracted_data?.table_rows?.length ?? 0), 0);
  const totalFields = results.reduce((s, d) => {
    const ext = d.extracted_data?.extracted_data ?? {};
    return s + Object.keys(ext).filter(k => !k.startsWith("_")).length;
  }, 0);
  const reviewCount = results.filter(d => d.needs_review).length;

  return (
    <AppLayout>
      <style>{`
        .hist-layout { 
          display: grid; 
          grid-template-columns: 340px 1fr; 
          gap: 18px; 
          align-items: start;
          height: calc(100vh - 140px);
        }
        @media (max-width: 700px) { .hist-layout { grid-template-columns: 1fr; height: auto; } }
        .job-list-col {
          height: 100%;
          overflow-y: auto;
          padding-right: 4px;
        }
        .job-detail-col {
          height: 100%;
          overflow-y: auto;
          padding-right: 4px;
        }
        .job-list { display: flex; flex-direction: column; gap: 5px; }
        .job-card {
          display: flex; align-items: center; gap: 10px;
          padding: 11px 13px; background: var(--surface);
          border: 1px solid var(--border); border-radius: 9px;
          cursor: pointer; transition: border-color 0.12s;
        }
        .job-card:hover { border-color: var(--border2); }
        .job-card.sel { border-color: var(--accent); background: var(--surface2); }
        .job-card.failed { border-color: var(--red,#ef4444)44; }
        .job-meta { flex: 1; min-width: 0; }
        .job-id-row { display: flex; align-items: center; gap: 7px; margin-bottom: 2px; }
        .job-id { font-size: 13px; font-weight: 600; color: var(--text1); }
        .job-sub { font-size: 11px; color: var(--text3); }
        .job-counts { display: flex; gap: 8px; margin-top: 3px; }
        .job-count { font-size: 11px; }
        .detail-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
        .detail-title { font-size: 15px; font-weight: 600; color: var(--text1); flex: 1; min-width: 80px; }
        .stat-bar { display: flex; gap: 16px; padding: 10px 14px; background: var(--surface2); border-radius: 8px; margin-bottom: 14px; flex-wrap: wrap; }
        .stat-item { display: flex; flex-direction: column; }
        .stat-val { font-size: 18px; font-weight: 700; color: var(--text1); line-height: 1; }
        .stat-lbl { font-size: 10px; color: var(--text4); margin-top: 2px; }
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
          {/* ── Job list ── */}
          <div className="job-list-col">
            <p className="label" style={{ marginBottom: 10 }}>{jobs.length} jobs</p>
            <div className="job-list">
              {jobs.map(job => (
                <div
                  key={job.id}
                  className={`job-card ${selectedJobId === job.id ? "sel" : ""} ${job.status === "failed" ? "failed" : ""}`}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <StatusIcon status={job.status} />
                  <div className="job-meta">
                    <div className="job-id-row">
                      <span className="job-id">Job #{job.id}</span>
                      <StatusBadge status={job.status} />
                      {job.schema_id && (
                        <span style={{ fontSize: 9, padding: "1px 5px", background: "var(--accent-dim)", color: "var(--accent)", borderRadius: 3, fontWeight: 600 }}>TPL</span>
                      )}
                    </div>
                    <div className="job-sub">{fmt(job.created_at)}</div>
                    <div className="job-counts">
                      <span className="job-count" style={{ color: "var(--text3)" }}>{job.total_docs} docs</span>
                      {job.successful > 0 && <span className="job-count" style={{ color: "var(--green)" }}>✓ {job.successful}</span>}
                      {job.failed > 0 && <span className="job-count" style={{ color: "var(--red)" }}>✗ {job.failed}</span>}
                      {(job as any).total_tokens > 0 && (
                        <span className="job-count" style={{ color: "var(--text3)" }}>
                          {((job as any).total_tokens / 1000).toFixed(1)}k tokens
                        </span>
                      )}
                      {job.total_time_sec > 0 && <span className="job-count" style={{ color: "var(--text3)" }}>{job.total_time_sec.toFixed(1)}s</span>}
                    </div>
                  </div>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--text4)" strokeWidth="2"><polyline points="9 18 15 12 9 6"/></svg>
                </div>
              ))}
            </div>
          </div>

          {/* ── Job detail ── */}
          <div className="job-detail-col">
            {selectedJob ? (
              <>
                <div className="detail-header">
                  <span className="detail-title">Job #{selectedJob.id}</span>
                  <StatusBadge status={selectedJob.status} />
                  {selectedJob.status === "completed" && (
                    <>
                      {jobHasTemplate && (
                        <button className="btn btn-primary btn-sm" onClick={() => handleExport(selectedJob.id, "template")}>
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
                  {selectedJob.status === "failed" && (
                    <span style={{ fontSize: 12, color: "var(--red,#ef4444)" }}>
                      This job failed — no output available
                    </span>
                  )}
                </div>

                {/* Stats bar */}
                {results.length > 0 && (
                  <div className="stat-bar">
                    <div className="stat-item">
                      <span className="stat-val">{results.length}</span>
                      <span className="stat-lbl">Documents</span>
                    </div>
                    <div className="stat-item">
                      <span className="stat-val" style={{ color: "var(--accent)" }}>{totalFields}</span>
                      <span className="stat-lbl">Fields extracted</span>
                    </div>
                    {totalRows > 0 && (
                      <div className="stat-item">
                        <span className="stat-val" style={{ color: "var(--green)" }}>{totalRows}</span>
                        <span className="stat-lbl">Table rows</span>
                      </div>
                    )}
                    {reviewCount > 0 && (
                      <div className="stat-item">
                        <span className="stat-val" style={{ color: "var(--amber,#f59e0b)" }}>{reviewCount}</span>
                        <span className="stat-lbl">Need review</span>
                      </div>
                    )}
                    {selectedJob.total_time_sec > 0 && (
                      <div className="stat-item">
                        <span className="stat-val">{selectedJob.total_time_sec.toFixed(1)}s</span>
                        <span className="stat-lbl">Total time</span>
                      </div>
                    )}
                  </div>
                )}

                {resultsLoading ? (
                  <div className="card" style={{ padding: 32, textAlign: "center" }}>
                    <svg className="animate-spin" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="2" style={{ margin: "0 auto 10px", display: "block" }}><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                    <p style={{ fontSize: 13, color: "var(--text3)" }}>Loading results…</p>
                  </div>
                ) : results.length === 0 && selectedJob.status !== "processing" ? (
                  <div className="card" style={{ padding: "32px", textAlign: "center" }}>
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5" style={{ margin: "0 auto 10px", display: "block" }}>
                      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                      <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                    <p style={{ fontWeight: 500, color: "var(--text1)" }}>No results found</p>
                    <p style={{ fontSize: 12, color: "var(--text3)", marginTop: 4 }}>
                      This job may have failed or been cancelled.
                      Check the status and try re-running the extraction.
                    </p>
                  </div>
                ) : (
                  results.map(doc => <DocCard key={doc.id} doc={doc} />)
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
