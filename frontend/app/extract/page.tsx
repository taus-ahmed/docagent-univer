"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import toast from "react-hot-toast";
import AppLayout from "@/components/layout/AppLayout";
import ResultsGrid from "@/components/extract/ResultsGrid";
import DriveTab from "@/components/extract/DriveTab";
import {
  extractApi, exportApi, templatesApi, schemasApi,
  type ColumnTemplate, type JobStatus, type DocumentResult,
} from "@/lib/api";
import Link from "next/link";

type SourceTab = "upload" | "folder" | "drive";

// ─── Additional options definition ────────────────────────────────────────────

const EXTRA_OPTIONS = [
  {
    id: "categorize",
    label: "Categorization",
    desc: "AI assigns a category to every line item or transaction",
    color: "#6366f1",
    icon: (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
        <line x1="7" y1="7" x2="7.01" y2="7"/>
      </svg>
    ),
  },
  {
    id: "graphs",
    label: "Charts & Graphs",
    desc: "Visual breakdown — pie and bar charts from extracted data",
    color: "#10b981",
    icon: (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <line x1="18" y1="20" x2="18" y2="10"/>
        <line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/>
        <line x1="2" y1="20" x2="22" y2="20"/>
      </svg>
    ),
  },
  {
    id: "summary",
    label: "AI Summary",
    desc: "3-line plain-English summary of the document contents",
    color: "#f59e0b",
    icon: (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="16" y1="13" x2="8" y2="13"/>
        <line x1="16" y1="17" x2="8" y2="17"/>
      </svg>
    ),
  },
  {
    id: "anomaly",
    label: "Anomaly Detection",
    desc: "Flag unusual values, duplicates or outliers",
    color: "#ef4444",
    icon: (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
        <line x1="12" y1="9" x2="12" y2="13"/>
        <line x1="12" y1="17" x2="12.01" y2="17"/>
      </svg>
    ),
  },
] as const;

type OptionId = typeof EXTRA_OPTIONS[number]["id"];

// ─── Category colour map ───────────────────────────────────────────────────────

const CAT_COLORS: Record<string, string> = {
  "Salary / Payroll": "#6366f1", "Sales Revenue": "#10b981", "Rent Received": "#f59e0b",
  "Interest Income": "#3b82f6", "Tax Refund": "#8b5cf6", "Loan Received": "#ec4899",
  "Transfer In": "#14b8a6", "Other Income": "#a3e635",
  "Rent / Lease": "#ef4444", "Payroll / Salaries": "#f97316", "Utilities": "#84cc16",
  "Insurance": "#06b6d4", "Loan Repayment": "#8b5cf6", "Bank Charges": "#6b7280",
  "Tax Payment": "#dc2626", "Supplier Payment": "#d97706", "Professional Fees": "#7c3aed",
  "Travel & Transport": "#0891b2", "Meals & Entertainment": "#16a34a",
  "Office & Supplies": "#ca8a04", "Software & Subscriptions": "#2563eb",
  "Marketing": "#db2777", "Equipment": "#475569", "Transfer Out": "#9ca3af",
  "ATM / Cash": "#64748b", "Cheque Payment": "#78716c", "Other Expense": "#94a3b8",
};
const CHART_COLORS = ["#6366f1","#10b981","#f59e0b","#ef4444","#3b82f6","#8b5cf6","#ec4899","#14b8a6"];
function catColor(c: string) { return CAT_COLORS[c] ?? "#94a3b8"; }

// ─── Inline SVG charts ─────────────────────────────────────────────────────────

function PieChart({ data, size = 140 }: { data: { label: string; value: number; color: string }[]; size?: number }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  if (!total) return null;
  const cx = size / 2, cy = size / 2, r = size * 0.38, inner = r * 0.52;
  let angle = -Math.PI / 2;
  const slices = data.map(d => {
    const sweep = (d.value / total) * 2 * Math.PI;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    angle += sweep;
    const x2 = cx + r * Math.cos(angle), y2 = cy + r * Math.sin(angle);
    return { ...d, path: `M${cx} ${cy} L${x1} ${y1} A${r} ${r} 0 ${sweep > Math.PI ? 1 : 0} 1 ${x2} ${y2}Z` };
  });
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {slices.map((s, i) => <path key={i} d={s.path} fill={s.color} opacity={0.88}/>)}
      <circle cx={cx} cy={cy} r={inner} fill="var(--surface1,#18181b)"/>
    </svg>
  );
}

function BarChart({ data, height = 100 }: { data: { label: string; value: number; color: string }[] ; height?: number }) {
  if (!data.length) return null;
  const max = Math.max(...data.map(d => d.value), 1);
  const w = 260, bw = Math.min(36, Math.floor(w / data.length) - 5);
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none">
      {data.map((d, i) => {
        const bh = (d.value / max) * (height - 22);
        const x = i * (bw + 5), y = height - 18 - bh;
        return (
          <g key={i}>
            <rect x={x} y={y} width={bw} height={bh} fill={d.color} rx={3} opacity={0.85}/>
            <text x={x + bw / 2} y={height - 3} textAnchor="middle" fontSize={7} fill="#71717a">
              {d.label.length > 7 ? d.label.slice(0, 6) + "…" : d.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ─── InsightsPanel ─────────────────────────────────────────────────────────────

function InsightsPanel({
  results, options, docType,
}: {
  results: DocumentResult[]; options: OptionId[]; docType: string;
}) {
  const [summary, setSummary] = useState("");
  const [anomalies, setAnomalies] = useState<string[]>([]);
  const [loadingSummary, setLoadingSummary] = useState(false);
  const [loadingAnomalies, setLoadingAnomalies] = useState(false);
  const didSummary = useRef(false);
  const didAnomaly = useRef(false);

  // Flatten all extracted fields and table rows from results
  const allFields: Record<string, string> = {};
  const tableRows: Record<string, string>[] = [];
  results.forEach(r => {
    const data = (r as any).extracted_data ?? {};
    const inner = data.extracted_data ?? {};
    Object.entries(inner).forEach(([k, v]: any) => {
      if (!k.startsWith("_label_")) {
        allFields[k] = typeof v === "object" ? (v?.value ?? "") : String(v ?? "");
      }
    });
    (data.table_rows ?? []).forEach((row: any) => tableRows.push(row));
  });

  const hasTable = tableRows.length > 0;

  // ── Categorization counts ─────────────────────────────────────────────────
  const catCount: Record<string, number> = {};
  const catAmount: Record<string, number> = {};
  if (options.includes("categorize") && hasTable) {
    tableRows.forEach(row => {
      const cat = row.Category ?? row.category ?? "Other Expense";
      catCount[cat] = (catCount[cat] ?? 0) + 1;
      const amt = parseFloat(String(
        row.Amount ?? row.Debit ?? row.Credit ?? row["Item Subtotal"] ?? row.Price ?? "0"
      ).replace(/[^0-9.-]/g, "")) || 0;
      catAmount[cat] = (catAmount[cat] ?? 0) + amt;
    });
  }
  const catPie = Object.entries(catCount).sort((a, b) => b[1] - a[1]).slice(0, 8)
    .map(([label, value]) => ({ label, value, color: catColor(label) }));
  const catBar = Object.entries(catAmount).filter(([,v]) => v > 0).sort((a,b) => b[1]-a[1]).slice(0, 7)
    .map(([label, value]) => ({ label, value: Math.round(value * 100) / 100, color: catColor(label) }));

  // ── Numeric fields for graphs ────────────────────────────────────────────
  const numericFields = Object.entries(allFields)
    .filter(([,v]) => !isNaN(parseFloat(v)) && parseFloat(v) > 0)
    .map(([k, v]) => ({ label: k, value: parseFloat(v) }))
    .sort((a, b) => b.value - a.value).slice(0, 6);
  const fieldBar = numericFields.map((f, i) => ({ ...f, color: CHART_COLORS[i % CHART_COLORS.length] }));
  const fieldPie = numericFields.map((f, i) => ({ ...f, color: CHART_COLORS[i % CHART_COLORS.length] }));

  // ── AI Summary ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!options.includes("summary") || didSummary.current || !Object.keys(allFields).length) return;
    didSummary.current = true;
    setLoadingSummary(true);
    const fieldStr = Object.entries(allFields).slice(0, 20).map(([k, v]) => `${k}: ${v}`).join("\n");
    fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514", max_tokens: 200,
        messages: [{ role: "user", content: `Summarise this ${docType} document in 2-3 plain English sentences. Be specific about key values. No bullet points.\n\n${fieldStr}` }],
      }),
    }).then(r => r.json())
      .then(d => setSummary(d?.content?.[0]?.text ?? ""))
      .catch(() => setSummary("Summary unavailable."))
      .finally(() => setLoadingSummary(false));
  }, [options.join(","), results.length]);

  // ── AI Anomaly ────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!options.includes("anomaly") || didAnomaly.current) return;
    didAnomaly.current = true;
    setLoadingAnomalies(true);
    const fieldStr = Object.entries(allFields).slice(0, 15).map(([k, v]) => `${k}: ${v}`).join("\n");
    const rowStr = tableRows.slice(0, 30).map((r, i) => `Row ${i + 1}: ${JSON.stringify(r)}`).join("\n");
    fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "claude-sonnet-4-20250514", max_tokens: 300,
        messages: [{ role: "user", content: `Analyse this extracted document data and identify anomalies, unusual values, duplicates or items needing review. Return a JSON array of strings, max 5 items. If nothing unusual return []. Return ONLY the JSON array.\n\nFields:\n${fieldStr}\n\nRows:\n${rowStr}` }],
      }),
    }).then(r => r.json())
      .then(d => {
        const text = d?.content?.[0]?.text ?? "[]";
        try { setAnomalies(JSON.parse(text.replace(/```json|```/g, "").trim())); } catch { setAnomalies([]); }
      })
      .catch(() => setAnomalies([]))
      .finally(() => setLoadingAnomalies(false));
  }, [options.join(","), results.length]);

  if (!options.length) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 14 }}>

      {/* Summary */}
      {options.includes("summary") && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#f59e0b18", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>AI Summary</span>
          </div>
          {loadingSummary ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text3)" }}>
              <svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
              Generating summary…
            </div>
          ) : (
            <p style={{ fontSize: 12.5, color: "var(--text2)", lineHeight: 1.65 }}>{summary || "No summary available."}</p>
          )}
        </div>
      )}

      {/* Categorization */}
      {options.includes("categorize") && catPie.length > 0 && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#6366f118", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>Categorization</span>
            <span style={{ fontSize: 10, color: "var(--text3)", marginLeft: "auto" }}>{tableRows.length} items</span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 14, alignItems: "center", marginBottom: 14 }}>
            <PieChart data={catPie} size={120}/>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {catPie.map((d, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 7, height: 7, borderRadius: 2, background: d.color, flexShrink: 0 }}/>
                  <span style={{ fontSize: 10.5, color: "var(--text2)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.label}</span>
                  <span style={{ fontSize: 10.5, color: "var(--text3)", fontWeight: 600 }}>{d.value}</span>
                </div>
              ))}
            </div>
          </div>

          {catBar.length > 0 && (
            <>
              <p style={{ fontSize: 10, color: "var(--text3)", marginBottom: 6 }}>Amount by category</p>
              <BarChart data={catBar} height={90}/>
            </>
          )}
        </div>
      )}

      {/* Graphs — shown when no categorization data or in addition */}
      {options.includes("graphs") && fieldBar.length > 0 && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#10b98118", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/></svg>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>Numeric Breakdown</span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 14, alignItems: "center", marginBottom: 14 }}>
            <PieChart data={fieldPie} size={110}/>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {fieldPie.map((d, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 7, height: 7, borderRadius: 2, background: d.color, flexShrink: 0 }}/>
                  <span style={{ fontSize: 10.5, color: "var(--text2)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.label}</span>
                  <span style={{ fontSize: 10.5, color: "var(--text3)", fontWeight: 600 }}>{d.value.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </div>
          <BarChart data={fieldBar} height={90}/>
          {hasTable && (
            <div style={{ marginTop: 10, display: "flex", gap: 5, flexWrap: "wrap" }}>
              {Object.keys(tableRows[0] ?? {}).slice(0, 6).map((col, i) => (
                <span key={i} style={{ fontSize: 9.5, padding: "2px 7px", borderRadius: 4, background: "var(--surface2)", color: "var(--text3)" }}>{col}</span>
              ))}
              {tableRows.length > 0 && <span style={{ fontSize: 9.5, color: "var(--text4)" }}>· {tableRows.length} rows</span>}
            </div>
          )}
        </div>
      )}

      {/* Anomaly Detection */}
      {options.includes("anomaly") && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#ef444418", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>Anomaly Detection</span>
          </div>
          {loadingAnomalies ? (
            <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text3)" }}>
              <svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
              Analysing for anomalies…
            </div>
          ) : anomalies.length === 0 ? (
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>
              <span style={{ fontSize: 12, color: "var(--text3)" }}>No anomalies detected</span>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {anomalies.map((a, i) => (
                <div key={i} style={{ display: "flex", gap: 8, padding: "7px 10px", background: "#ef444410", borderRadius: 6, border: "1px solid #ef444428" }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" style={{ flexShrink: 0, marginTop: 2 }}><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                  <span style={{ fontSize: 11.5, color: "var(--text2)", lineHeight: 1.5 }}>{a}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function ExtractPage() {
  const [selectedTemplate, setSelectedTemplate] = useState<ColumnTemplate | null>(null);
  const [activeTab, setActiveTab] = useState<SourceTab>("upload");
  const [files, setFiles] = useState<File[]>([]);
  const [folderPath, setFolderPath] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [results, setResults] = useState<DocumentResult[]>([]);
  const [selectedOptions, setSelectedOptions] = useState<OptionId[]>([]);
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
    extractApi.getResults(activeJobId!).then(data => { setResults(data); setIsExtracting(false); });
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

  function toggleOption(id: OptionId) {
    setSelectedOptions(prev => prev.includes(id) ? prev.filter(o => o !== id) : [...prev, id]);
  }

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
    setFiles([]); setResults([]); setActiveJobId(null);
    prevStatus.current = ""; setIsExtracting(false);
  }

  const isRunning = jobStatus?.status === "processing" || jobStatus?.status === "pending";
  const isDone = jobStatus?.status === "completed";
  const isFailed = jobStatus?.status === "failed";
  const hasResults = results.length > 0;
  const docType = selectedTemplate?.document_type ?? "document";

  return (
    <AppLayout>
      <style>{`
        .ex-layout { display: grid; grid-template-columns: 296px 1fr; gap: 18px; align-items: start; }
        .ex-left { display: flex; flex-direction: column; gap: 14px; }

        .tpl-picker-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
        .tpl-list { display: flex; flex-direction: column; gap: 4px; max-height: 240px; overflow-y: auto; }
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
        .tpl-name { flex: 1; font-size: 12.5px; color: var(--text2); font-weight: 450; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .tpl-row.sel .tpl-name { color: var(--text1); font-weight: 500; }
        .tpl-type { font-size: 10px; padding: 2px 6px; background: var(--surface3); border-radius: 4px; color: var(--text3); flex-shrink: 0; }
        .tpl-row.sel .tpl-type { background: var(--surface4); color: var(--accent); }
        .tpl-none { padding: 10px; border: 1px dashed var(--border); border-radius: 7px; text-align: center; font-size: 12px; color: var(--text4); }

        .src-tabs { display: flex; gap: 1px; background: var(--surface2); border-radius: 7px; padding: 3px; margin-bottom: 12px; }
        .src-tab { flex: 1; padding: 5px; border-radius: 5px; text-align: center; font-size: 12px; font-weight: 500; color: var(--text3); cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 5px; }
        .src-tab.active { background: var(--surface3); color: var(--text1); }

        .dropzone { border: 1.5px dashed var(--border2); border-radius: 9px; padding: 22px 16px; text-align: center; cursor: pointer; transition: border-color 0.15s, background 0.15s; }
        .dropzone:hover, .dropzone.drag { border-color: var(--accent); background: var(--accent-dim); }
        .dz-icon { width: 36px; height: 36px; border-radius: 9px; background: var(--surface2); margin: 0 auto 10px; display: flex; align-items: center; justify-content: center; }

        .file-item { display: flex; align-items: center; gap: 7px; padding: 6px 9px; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; margin-top: 5px; }
        .file-name { flex: 1; font-size: 12px; color: var(--text2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .file-size { font-size: 10px; color: var(--text3); flex-shrink: 0; }

        .progress-bar { height: 3px; background: var(--surface3); border-radius: 2px; overflow: hidden; margin: 6px 0 4px; }
        .progress-fill { height: 100%; border-radius: 2px; }
        .progress-fill.running { background: var(--accent); animation: indeterminate 1.4s ease-in-out infinite; width: 50% !important; }
        .progress-fill.done { background: var(--green); width: 100% !important; }
        .progress-fill.failed { background: var(--red); width: 100% !important; }
        .job-stats { display: flex; gap: 12px; flex-wrap: wrap; }
        .job-stat { font-size: 11px; color: var(--text3); }
        .job-stat b { font-weight: 600; }
        .export-row { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }

        /* Options grid */
        .opt-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
        .opt-card {
          padding: 9px 10px; border-radius: 8px;
          border: 1.5px solid var(--border); background: var(--surface2);
          cursor: pointer; transition: border-color 0.14s, background 0.14s;
          user-select: none;
        }
        .opt-card:hover { border-color: var(--border2); }
        .opt-card.on { border-color: var(--accent); background: var(--accent-dim); }
        .opt-top { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
        .opt-ico { width: 21px; height: 21px; border-radius: 5px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .opt-lbl { font-size: 11px; font-weight: 600; color: var(--text2); flex: 1; }
        .opt-card.on .opt-lbl { color: var(--text1); }
        .opt-chk { width: 13px; height: 13px; border-radius: 3px; border: 1.5px solid var(--border2); display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .opt-card.on .opt-chk { background: var(--accent); border-color: var(--accent); }
        .opt-desc { font-size: 9.5px; color: var(--text4); line-height: 1.4; padding-left: 27px; }

        /* Right panel welcome */
        .welcome-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
        .welcome-stat { padding: 14px; border-radius: 9px; background: var(--surface2); border: 1px solid var(--border); }
        .welcome-stat-val { font-size: 20px; font-weight: 700; color: var(--text1); }
        .welcome-stat-lbl { font-size: 10.5px; color: var(--text3); margin-top: 2px; }

        @keyframes indeterminate {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(300%); }
        }
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
        {/* ── Left column ── */}
        <div className="ex-left">

          {/* Template picker */}
          <div className="card" style={{ padding: 14 }}>
            <div className="tpl-picker-header">
              <span className="label">Template</span>
              <Link href="/templates" className="btn btn-ghost btn-sm" style={{ fontSize: 11 }}>Manage</Link>
            </div>
            {templates.length === 0 ? (
              <div className="tpl-none">No templates — <Link href="/templates/new" style={{ color: "var(--accent)" }}>create one</Link></div>
            ) : (
              <div className="tpl-list">
                {templates.map(t => (
                  <div key={t.id} className={`tpl-row ${selectedTemplate?.id === t.id ? "sel" : ""}`}
                    onClick={() => setSelectedTemplate(selectedTemplate?.id === t.id ? null : t)}>
                    <div className="tpl-dot"/>
                    <span className="tpl-name">{t.name}</span>
                    <span className="tpl-type">{t.document_type}</span>
                  </div>
                ))}
              </div>
            )}
            {selectedTemplate && (
              <div style={{ marginTop: 10, padding: "7px 10px", background: "var(--surface2)", borderRadius: 6, fontSize: 11, color: "var(--text3)" }}>
                {selectedTemplate.columns.length} columns · {selectedTemplate.document_type}
                {(selectedTemplate as any).description && (
                  <span style={{ marginLeft: 6, color: "var(--green)" }}>· layout saved</span>
                )}
              </div>
            )}
          </div>

          {/* Additional options — always visible, not dependent on template */}
          {!hasResults && (
            <div className="card" style={{ padding: 14 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <span className="label">Additional Options</span>
                {selectedOptions.length > 0 && (
                  <button style={{ fontSize: 10, color: "var(--text3)", background: "none", border: "none", cursor: "pointer" }}
                    onClick={() => setSelectedOptions([])}>Clear</button>
                )}
              </div>
              <div className="opt-grid">
                {EXTRA_OPTIONS.map(opt => (
                  <div key={opt.id} className={`opt-card ${selectedOptions.includes(opt.id) ? "on" : ""}`}
                    onClick={() => toggleOption(opt.id)}>
                    <div className="opt-top">
                      <div className="opt-ico" style={{ background: opt.color + "18" }}>
                        <span style={{ color: opt.color }}>{opt.icon}</span>
                      </div>
                      <span className="opt-lbl">{opt.label}</span>
                      <div className="opt-chk">
                        {selectedOptions.includes(opt.id) && (
                          <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3.5"><polyline points="20 6 9 17 4 12"/></svg>
                        )}
                      </div>
                    </div>
                    <p className="opt-desc">{opt.desc}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Documents uploader */}
          {!isRunning && !hasResults && (
            <div className="card" style={{ padding: 14 }}>
              <span className="label" style={{ display: "block", marginBottom: 10 }}>Documents</span>
              <div className="src-tabs">
                {(["upload","folder","drive"] as SourceTab[]).map(tab => (
                  <div key={tab} className={`src-tab ${activeTab === tab ? "active" : ""}`} onClick={() => setActiveTab(tab)}>
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
                    <input {...getInputProps()}/>
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
                      <button onClick={() => setFiles(p => p.filter(x => x.name !== f.name))}
                        style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 2 }}>
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                      </button>
                    </div>
                  ))}
                </>
              )}

              {activeTab === "folder" && (
                <div>
                  <input className="input" placeholder="C:\Users\Admin\Documents\invoices"
                    value={folderPath} onChange={e => setFolderPath(e.target.value)}/>
                  <p style={{ fontSize: 11, color: "var(--text4)", marginTop: 6 }}>Local folder — all PDFs and images inside will be uploaded</p>
                </div>
              )}

              {activeTab === "drive" && (
                <DriveTab selectedTemplate={selectedTemplate} clientId={clientId}
                  onJobStarted={(jobId) => { setActiveJobId(jobId); setIsExtracting(true); }}/>
              )}
            </div>
          )}

          {/* Extract button */}
          {!isRunning && !hasResults && activeTab !== "drive" && (
            <button className="btn btn-primary btn-full btn-lg" onClick={handleExtract}
              disabled={isExtracting || !selectedTemplate || (activeTab === "upload" && !files.length)}>
              {isExtracting ? (
                <><svg className="animate-spin" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Starting…</>
              ) : (
                <>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                  Extract {files.length > 0 ? `${files.length} file${files.length > 1 ? "s" : ""}` : "documents"}
                  {selectedOptions.length > 0 && (
                    <span style={{ marginLeft: 5, fontSize: 10, padding: "1px 6px", background: "rgba(255,255,255,0.18)", borderRadius: 10 }}>
                      +{selectedOptions.length}
                    </span>
                  )}
                </>
              )}
            </button>
          )}

          {/* Job status card */}
          {activeJobId && (
            <div className="card" style={{ padding: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                {isRunning && <svg className="animate-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>}
                {isDone && <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>}
                {isFailed && <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>}
                <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text1)" }}>
                  {isRunning ? "Extracting…" : isDone ? "Extraction complete" : "Extraction failed"}
                </span>
              </div>
              <div className="progress-bar">
                <div className={`progress-fill ${isRunning ? "running" : isDone ? "done" : "failed"}`}/>
              </div>
              {jobStatus && (
                <div className="job-stats">
                  <span className="job-stat"><b>{jobStatus.total_docs}</b> docs</span>
                  {jobStatus.successful > 0 && <span className="job-stat" style={{ color: "var(--green)" }}><b>{jobStatus.successful}</b> ok</span>}
                  {jobStatus.failed > 0 && <span className="job-stat" style={{ color: "var(--red)" }}><b>{jobStatus.failed}</b> failed</span>}
                  {isDone && <span className="job-stat"><b>{(jobStatus.total_time_sec ?? 0).toFixed(1)}s</b></span>}
                </div>
              )}
              {isFailed && jobStatus?.error_message && (
                <p style={{ fontSize: 11, color: "var(--red)", marginTop: 8 }}>{jobStatus.error_message}</p>
              )}
              {isDone && activeJobId && (
                <div className="export-row">
                  {selectedTemplate && (
                    <button className="btn btn-primary btn-sm" onClick={async () => {
                      try {
                        const blob = await exportApi.templateExport(activeJobId);
                        exportApi.downloadBlob(blob, `job_${activeJobId}_results.xlsx`);
                        toast.success("Downloaded");
                      } catch { toast.error("Export failed"); }
                    }}>
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                      Template Excel
                    </button>
                  )}
                  <button className="btn btn-secondary btn-sm" onClick={async () => {
                    try {
                      const blob = await exportApi.combined({ job_id: activeJobId, template_id: selectedTemplate?.id });
                      exportApi.downloadBlob(blob, `extraction_${activeJobId}.xlsx`);
                    } catch { toast.error("Export failed"); }
                  }}>Flat Excel</button>
                  <button className="btn btn-secondary btn-sm" onClick={async () => {
                    try {
                      const blob = await exportApi.perFile({ job_id: activeJobId, template_id: selectedTemplate?.id });
                      exportApi.downloadBlob(blob, `extraction_${activeJobId}_perfile.xlsx`);
                    } catch { toast.error("Export failed"); }
                  }}>Per-file</button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Right panel ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {hasResults ? (
            <>
              <ResultsGrid results={results} jobId={activeJobId!} template={selectedTemplate}/>
              {selectedOptions.length > 0 && (
                <InsightsPanel results={results} options={selectedOptions} docType={docType}/>
              )}
            </>
          ) : (
            <div className="card" style={{ minHeight: 380 }}>
              {isRunning ? (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 380, padding: 40, gap: 12 }}>
                  <svg className="animate-spin" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
                  <p style={{ fontSize: 14, fontWeight: 500, color: "var(--text1)" }}>Processing documents…</p>
                  <p style={{ fontSize: 12, color: "var(--text3)" }}>AI extraction in progress</p>
                  {selectedOptions.length > 0 && (
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "center", marginTop: 4 }}>
                      {selectedOptions.map(id => {
                        const opt = EXTRA_OPTIONS.find(o => o.id === id)!;
                        return (
                          <span key={id} style={{ fontSize: 10, padding: "2px 8px", borderRadius: 10, background: opt.color + "18", color: opt.color, fontWeight: 500 }}>
                            {opt.label}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              ) : selectedTemplate ? (
                /* Template selected — show preview */
                <div style={{ padding: 28 }}>
                  <div style={{ display: "flex", alignItems: "flex-start", gap: 14, paddingBottom: 20, marginBottom: 20, borderBottom: "1px solid var(--border)" }}>
                    <div style={{ width: 42, height: 42, borderRadius: 11, background: "var(--accent-dim)", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                    </div>
                    <div>
                      <p style={{ fontSize: 15, fontWeight: 600, color: "var(--text1)", marginBottom: 3 }}>{selectedTemplate.name}</p>
                      <p style={{ fontSize: 12, color: "var(--text3)" }}>{selectedTemplate.document_type} · {selectedTemplate.columns.length} columns</p>
                      {(selectedTemplate as any).description && <span style={{ fontSize: 10, color: "var(--green)" }}>Layout saved</span>}
                    </div>
                  </div>

                  <div className="welcome-grid" style={{ marginBottom: selectedOptions.length ? 20 : 0 }}>
                    <div className="welcome-stat">
                      <div className="welcome-stat-val">{selectedTemplate.columns.length}</div>
                      <div className="welcome-stat-lbl">Columns to extract</div>
                    </div>
                    <div className="welcome-stat">
                      <div className="welcome-stat-val">{files.length || "—"}</div>
                      <div className="welcome-stat-lbl">Files selected</div>
                    </div>
                    <div className="welcome-stat">
                      <div className="welcome-stat-val" style={{ color: selectedOptions.length ? "var(--accent)" : "var(--text3)" }}>
                        {selectedOptions.length || "0"}
                      </div>
                      <div className="welcome-stat-lbl">Extra analyses</div>
                    </div>
                    <div className="welcome-stat">
                      <div className="welcome-stat-val" style={{ fontSize: 13 }}>{selectedTemplate.document_type}</div>
                      <div className="welcome-stat-lbl">Document type</div>
                    </div>
                  </div>

                  {selectedOptions.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                      <p style={{ fontSize: 10.5, color: "var(--text3)", marginBottom: 4 }}>Will run after extraction:</p>
                      {selectedOptions.map(id => {
                        const opt = EXTRA_OPTIONS.find(o => o.id === id)!;
                        return (
                          <div key={id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 12px", borderRadius: 8, background: opt.color + "0e", border: `1px solid ${opt.color}28` }}>
                            <div style={{ width: 22, height: 22, borderRadius: 5, background: opt.color + "18", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                              <span style={{ color: opt.color }}>{opt.icon}</span>
                            </div>
                            <div>
                              <p style={{ fontSize: 12, fontWeight: 600, color: "var(--text1)" }}>{opt.label}</p>
                              <p style={{ fontSize: 10, color: "var(--text3)" }}>{opt.desc}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {!files.length && (
                    <p style={{ fontSize: 12, color: "var(--text4)", textAlign: "center", marginTop: 24 }}>Add documents on the left to begin</p>
                  )}
                </div>
              ) : (
                /* No template selected — welcome + feature preview */
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 380, padding: "48px 40px", textAlign: "center" }}>
                  <div style={{ width: 46, height: 46, borderRadius: 12, background: "var(--surface2)", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 14 }}>
                    <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                  </div>
                  <p style={{ fontSize: 14, fontWeight: 500, color: "var(--text2)" }}>Select a template to start</p>
                  <p style={{ fontSize: 12, color: "var(--text4)", marginTop: 4, marginBottom: 28 }}>The template defines which columns appear in results</p>

                  <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%", maxWidth: 320, textAlign: "left" }}>
                    <p style={{ fontSize: 10.5, color: "var(--text3)", marginBottom: 2 }}>Available after extraction:</p>
                    {EXTRA_OPTIONS.map(opt => (
                      <div key={opt.id} style={{ display: "flex", alignItems: "flex-start", gap: 9, opacity: 0.65 }}>
                        <div style={{ width: 22, height: 22, borderRadius: 6, background: opt.color + "18", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, marginTop: 1 }}>
                          <span style={{ color: opt.color }}>{opt.icon}</span>
                        </div>
                        <div>
                          <p style={{ fontSize: 12, fontWeight: 600, color: "var(--text2)" }}>{opt.label}</p>
                          <p style={{ fontSize: 10.5, color: "var(--text4)" }}>{opt.desc}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
