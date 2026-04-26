"use client";

import { useState, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import toast from "react-hot-toast";
import AppLayout from "@/components/layout/AppLayout";
import ResultsGrid from "@/components/extract/ResultsGrid";
import DriveTab from "@/components/extract/DriveTab";
import { extractApi, exportApi, templatesApi, schemasApi, type ColumnTemplate, type JobStatus, type DocumentResult } from "@/lib/api";
import Link from "next/link";

type SourceTab = "upload" | "folder" | "drive";

export default function ExtractPage() {
  const [selectedTemplate, setSelectedTemplate] = useState<ColumnTemplate | null>(null);
  const [activeTab, setActiveTab] = useState<SourceTab>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [folderPath, setFolderPath] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [results, setResults] = useState<DocumentResult[]>([]);
  const prevStatus = useRef("");

  const { data: templates = [] } = useQuery<ColumnTemplate[]>({
    queryKey: ["templates"],
    queryFn: () => templatesApi.list(),
  });

  const { data: schemas = [] } = useQuery({
    queryKey: ["schemas"],
    queryFn: schemasApi.list,
  });

  const { data: jobStatus } = useQuery<JobStatus>({
    queryKey: ["job", activeJobId],
    queryFn: () => extractApi.getJob(activeJobId!),
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "processing" || s === "pending" ? 2000 : false;
    },
    staleTime: 0,
  });

  if (jobStatus?.status === "completed" && prevStatus.current !== "completed") {
    prevStatus.current = "completed";
    extractApi.getResults(activeJobId!).then(data => {
      setResults(data);
      setIsExtracting(false);
    });
  }
  if (jobStatus?.status === "failed" && prevStatus.current !== "failed") {
    prevStatus.current = "failed";
    setIsExtracting(false);
  }
  if (jobStatus?.status) prevStatus.current = jobStatus.status;

  const onDrop = useCallback((accepted: File[]) => {
    setFiles(prev => {
      const names = new Set(prev.map(f => f.name));
      return [...prev, ...accepted.filter(f => !names.has(f.name))];
    });
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"], "image/*": [".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"] },
    multiple: true,
  });

  const clientId = schemas[0]?.client_id ?? "demo_001";

  async function handleExtract() {
    if (activeTab === "upload" && !files.length) return toast.error("Add files first");
    if (!selectedTemplate) return toast.error("Select a template first");

    setIsExtracting(true);
    setResults([]);
    prevStatus.current = "";

    try {
      const res = await extractApi.upload(files, clientId, selectedTemplate.id);
      setActiveJobId(res.job_id);
      toast.success(`Extraction started — ${res.total_files} file(s)`);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? "Upload failed");
      setIsExtracting(false);
    }
  }

  function reset() {
    setFiles([]);
    setResults([]);
    setActiveJobId(null);
    prevStatus.current = "";
    setIsExtracting(false);
  }

  const isRunning = jobStatus?.status === "processing" || jobStatus?.status === "pending";
  const isDone = jobStatus?.status === "completed";
  const isFailed = jobStatus?.status === "failed";
  const hasResults = results.length > 0;

  return (
    <AppLayout>
      <style>{`
        .ex-layout { display: grid; grid-template-columns: 296px 1fr; gap: 18px; align-items: start; }
        .ex-left { display: flex; flex-direction: column; gap: 14px; }

        .tpl-picker { }
        .tpl-picker-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
        .tpl-list { display: flex; flex-direction: column; gap: 4px; }
        .tpl-row {
          display: flex; align-items: center; gap: 9px;
          padding: 8px 10px; border-radius: 7px;
          border: 1px solid var(--border); background: var(--surface2);
          cursor: pointer; transition: border-color 0.12s;
        }
        .tpl-row:hover { border-color: var(--border2); }
        .tpl-row.sel { border-color: var(--accent); background: var(--accent-dim); }
        .tpl-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--border2); flex-shrink: 0; }
        .tpl-row.sel .tpl-dot { background: var(--accent); }
        .tpl-name { flex: 1; font-size: 12.5px; color: var(--text2); font-weight: 450; }
        .tpl-row.sel .tpl-name { color: var(--text1); font-weight: 500; }
        .tpl-type { font-size: 10px; padding: 2px 6px; background: var(--surface3); border-radius: 4px; color: var(--text3); }
        .tpl-row.sel .tpl-type { background: var(--surface4); color: var(--accent); }
        .tpl-none {
          padding: 10px; border: 1px dashed var(--border); border-radius: 7px;
          text-align: center; font-size: 12px; color: var(--text4);
        }

        .src-tabs { display: flex; gap: 1px; background: var(--surface2); border-radius: 7px; padding: 3px; margin-bottom: 12px; }
        .src-tab { flex: 1; padding: 5px; border-radius: 5px; text-align: center; font-size: 12px; font-weight: 500; color: var(--text3); cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 5px; }
        .src-tab.active { background: var(--surface3); color: var(--text1); }

        .dropzone {
          border: 1.5px dashed var(--border2); border-radius: 9px;
          padding: 22px 16px; text-align: center; cursor: pointer;
          transition: border-color 0.15s, background 0.15s;
        }
        .dropzone:hover, .dropzone.drag { border-color: var(--accent); background: var(--accent-dim); }
        .dz-icon {
          width: 36px; height: 36px; border-radius: 9px;
          background: var(--surface2); margin: 0 auto 10px;
          display: flex; align-items: center; justify-content: center;
        }
        .drag .dz-icon { background: var(--accent-dim); }

        .file-item {
          display: flex; align-items: center; gap: 7px;
          padding: 6px 9px; background: var(--surface2);
          border: 1px solid var(--border); border-radius: 6px; margin-top: 5px;
        }
        .file-name { flex: 1; font-size: 12px; color: var(--text2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .file-size { font-size: 10px; color: var(--text3); flex-shrink: 0; }

        .progress-wrap { margin-top: 4px; }
        .progress-bar { height: 3px; background: var(--surface3); border-radius: 2px; overflow: hidden; }
        .progress-fill { height: 100%; border-radius: 2px; }
        .progress-fill.running { background: var(--accent); animation: indeterminate 1.4s ease-in-out infinite; width: 50% !important; }
        .progress-fill.done { background: var(--green); width: 100% !important; }
        .progress-fill.failed { background: var(--red); width: 100% !important; }

        .job-stats { display: flex; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
        .job-stat { font-size: 11px; color: var(--text3); }
        .job-stat b { font-weight: 600; }

        .right-empty {
          card min-height: 400px;
          display: flex; flex-direction: column;
          align-items: center; justify-content: center;
          padding: 48px 32px; text-align: center;
        }
        .empty-icon {
          width: 48px; height: 48px; border-radius: 12px;
          background: var(--surface2); display: flex;
          align-items: center; justify-content: center; margin-bottom: 14px;
        }

        .export-row { display: flex; gap: 8px; margin-top: 12px; }
      `}</style>

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 22 }}>
        <div>
          <h1 className="page-title">Extract</h1>
          <p className="page-sub">Select a template · upload documents · extract</p>
        </div>
        {hasResults && (
          <button className="btn btn-secondary btn-sm" onClick={reset}>New extraction</button>
        )}
      </div>

      <div className="ex-layout">
        {/* ── Left panel ── */}
        <div className="ex-left">

          {/* Template picker */}
          <div className="card" style={{ padding: 14 }}>
            <div className="tpl-picker-header">
              <span className="label">Template</span>
              <Link href="/templates" className="btn btn-ghost btn-sm" style={{ fontSize: 11 }}>
                Manage
              </Link>
            </div>

            {templates.length === 0 ? (
              <div className="tpl-none">
                No templates yet —{" "}
                <Link href="/templates/new" style={{ color: "var(--accent)" }}>create one</Link>
              </div>
            ) : (
              <div className="tpl-list">
                {templates.map(t => (
                  <div
                    key={t.id}
                    className={`tpl-row ${selectedTemplate?.id === t.id ? "sel" : ""}`}
                    onClick={() => setSelectedTemplate(selectedTemplate?.id === t.id ? null : t)}
                  >
                    <div className="tpl-dot" />
                    <span className="tpl-name">{t.name}</span>
                    <span className="tpl-type">{t.document_type}</span>
                  </div>
                ))}
              </div>
            )}

            {selectedTemplate && (
              <div style={{ marginTop: 10, padding: "7px 10px", background: "var(--surface2)", borderRadius: 6, fontSize: 11, color: "var(--text3)" }}>
                {selectedTemplate.columns.length} columns · {selectedTemplate.document_type}
              </div>
            )}
          </div>

          {/* Source selector */}
          {!isRunning && !hasResults && (
            <div className="card" style={{ padding: 14 }}>
              <span className="label" style={{ display: "block", marginBottom: 10 }}>Documents</span>

              <div className="src-tabs">
                {(["upload", "folder", "drive"] as SourceTab[]).map(tab => (
                  <div
                    key={tab}
                    className={`src-tab ${activeTab === tab ? "active" : ""}`}
                    onClick={() => setActiveTab(tab)}
                  >
                    {tab === "upload" && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>}
                    {tab === "folder" && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>}
                    {tab === "drive" && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>}
                    {tab.charAt(0).toUpperCase() + tab.slice(1)}
                  </div>
                ))}
              </div>

              {activeTab === "upload" && (
                <>
                  <div {...getRootProps()} className={`dropzone ${isDragActive ? "drag" : ""}`}>
                    <input {...getInputProps()} />
                    <div className="dz-icon">
                      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
                    </div>
                    <p style={{ fontSize: 12.5, fontWeight: 500, color: "var(--text2)", marginBottom: 2 }}>
                      {isDragActive ? "Drop files here" : "Drop files or click to browse"}
                    </p>
                    <p style={{ fontSize: 11, color: "var(--text4)" }}>PDF, PNG, JPG, TIFF — 50MB max</p>
                  </div>
                  {files.map(f => (
                    <div key={f.name} className="file-item">
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                      <span className="file-name">{f.name}</span>
                      <span className="file-size">{(f.size / 1024).toFixed(0)} KB</span>
                      <button onClick={() => setFiles(p => p.filter(x => x.name !== f.name))} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 2 }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                      </button>
                    </div>
                  ))}
                </>
              )}

              {activeTab === "folder" && (
                <div>
                  <input
                    className="input"
                    placeholder="C:\Users\Admin\Documents\invoices"
                    value={folderPath}
                    onChange={e => setFolderPath(e.target.value)}
                  />
                  <p style={{ fontSize: 11, color: "var(--text4)", marginTop: 6 }}>Local folder — all PDFs and images inside will be uploaded</p>
                </div>
              )}

              {activeTab === "drive" && (
                <DriveTab
                  selectedTemplate={selectedTemplate}
                  clientId={clientId}
                  onJobStarted={(jobId) => { setActiveJobId(jobId); setIsExtracting(true); }}
                />
              )}
            </div>
          )}

          {/* Extract button */}
          {!isRunning && !hasResults && activeTab !== "drive" && (
            <button
              className="btn btn-primary btn-full btn-lg"
              onClick={handleExtract}
              disabled={isExtracting || !selectedTemplate || (activeTab === "upload" && !files.length)}
            >
              {isExtracting ? (
                <><svg className="animate-spin" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Starting…</>
              ) : (
                <><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                Extract {files.length > 0 ? `${files.length} file${files.length > 1 ? "s" : ""}` : "documents"}</>
              )}
            </button>
          )}

          {/* Job status */}
          {activeJobId && (
            <div className="card" style={{ padding: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
                {isRunning && <svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>}
                {isDone && <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>}
                {isFailed && <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>}
                <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text1)" }}>
                  {isRunning ? "Extracting…" : isDone ? "Extraction complete" : "Extraction failed"}
                </span>
              </div>
              <div className="progress-bar">
                <div className={`progress-fill ${isRunning ? "running" : isDone ? "done" : "failed"}`} />
              </div>
              {jobStatus && (
                <div className="job-stats">
                  <span className="job-stat"><b>{jobStatus.total_docs}</b> docs</span>
                  {jobStatus.successful > 0 && <span className="job-stat" style={{ color: "var(--green)" }}><b>{jobStatus.successful}</b> ok</span>}
                  {jobStatus.failed > 0 && <span className="job-stat" style={{ color: "var(--red)" }}><b>{jobStatus.failed}</b> failed</span>}
                  {isDone && <span className="job-stat"><b>{jobStatus.total_time_sec.toFixed(1)}s</b></span>}
                </div>
              )}
              {isFailed && jobStatus?.error_message && (
                <p style={{ fontSize: 11, color: "var(--red)", marginTop: 8 }}>{jobStatus.error_message}</p>
              )}
              {isDone && activeJobId && (
                <div className="export-row">
                  <button className="btn btn-primary btn-sm" style={{ flex: 1 }} onClick={async () => {
                    try {
                      const blob = await exportApi.combined({ job_id: activeJobId, template_id: selectedTemplate?.id });
                      exportApi.downloadBlob(blob, `extraction_${activeJobId}.xlsx`);
                    } catch { toast.error("Export failed"); }
                  }}>
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Excel
                  </button>
                  <button className="btn btn-secondary btn-sm" style={{ flex: 1 }} onClick={async () => {
                    try {
                      const blob = await exportApi.perFile({ job_id: activeJobId, template_id: selectedTemplate?.id });
                      exportApi.downloadBlob(blob, `extraction_${activeJobId}_perfile.xlsx`);
                    } catch { toast.error("Export failed"); }
                  }}>
                    Per-file
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Right panel — results ── */}
        <div>
          {hasResults ? (
            <ResultsGrid results={results} jobId={activeJobId!} template={selectedTemplate} />
          ) : (
            <div className="card" style={{ minHeight: 380, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 32px", textAlign: "center" }}>
              {isRunning ? (
                <>
                  <svg className="animate-spin" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5" style={{ marginBottom: 16 }}><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                  <p style={{ fontSize: 14, fontWeight: 500, color: "var(--text1)" }}>Processing documents…</p>
                  <p style={{ fontSize: 12, color: "var(--text3)", marginTop: 4 }}>AI extraction in progress</p>
                </>
              ) : (
                <>
                  <div style={{ width: 48, height: 48, borderRadius: 12, background: "var(--surface2)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                  </div>
                  <p style={{ fontSize: 14, fontWeight: 500, color: "var(--text2)" }}>
                    {selectedTemplate ? `Ready — using "${selectedTemplate.name}"` : "Select a template to start"}
                  </p>
                  <p style={{ fontSize: 12, color: "var(--text4)", marginTop: 4 }}>
                    {selectedTemplate
                      ? `Results will show ${selectedTemplate.columns.length} columns`
                      : "The template defines which columns appear in results"}
                  </p>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
