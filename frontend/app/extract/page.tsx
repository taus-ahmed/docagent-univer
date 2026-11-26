"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import toast from "react-hot-toast";
import AppLayout from "@/components/layout/AppLayout";
import ResultsGrid from "@/components/extract/ResultsGrid";
import JobResultsLayout from "@/components/extract/JobResultsLayout";
import { templateUsedLabel } from "@/lib/jobTemplate";
import { useJobTemplate } from "@/lib/useJobTemplate";
import { jobModels, plainStatus } from "@/lib/jobModel";
import DriveTab from "@/components/extract/DriveTab";
import TemplatePreview from "@/components/extract/TemplatePreview";
import SampleDocsPanel from "@/components/extract/SampleDocsPanel";
import { bars, emptyReason, reviewBanner, type ChartsResponse } from "@/lib/charts";
import { OPTION_INFO, loadRemembered, optionState, saveRemembered, toggle, type OptionId as OptionsId } from "@/lib/options";
import {
  extractApi, templatesApi, schemasApi,
  type ColumnTemplate, type JobStatus, type DocumentResult,
} from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import {
  type PendingFile, addFiles, clearPasswords, filesOf, passwordsOf, removeFile, setPassword,
} from "@/lib/uploadFiles";
import { mayCancel } from "@/lib/permissions";
import { DEMO_OPTION_UNAVAILABLE, apiErrorText, jobErrorText } from "@/lib/demo-error";
import Link from "next/link";

type SourceTab = "upload" | "folder" | "drive";

// ─── Additional options definition ────────────────────────────────────────────

const EXTRA_OPTIONS = [
  {
    id: "categorize",
    label: "Categorization",
    desc: "Sort line items using your rules first.",
    cost: "AI only for unmatched rows.",
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
    desc: "Spend and trends by currency.",
    cost: "No AI call.",
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
    desc: "Counts, totals and dates.",
    cost: "No AI call.",
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
    id: "narrative",
    label: "Written summary (AI)",
    desc: "Turn the summary into prose.",
    cost: "One AI call per document.",
    color: "#d97706",
    icon: (
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>
      </svg>
    ),
  },
  {
    id: "anomaly",
    label: "Anomaly Detection",
    desc: "Flag duplicates, gaps, and outliers.",
    cost: "No AI call.",
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
  // Subcategory variants
  "Accommodation": "#0891b2", "Lodging": "#0891b2",
  "Meals": "#16a34a", "Meals - Business": "#15803d",
  "Airfare": "#3b82f6",
};
const CHART_COLORS = ["#6366f1","#10b981","#f59e0b","#ef4444","#3b82f6","#8b5cf6","#ec4899","#14b8a6"];

// Match category to color — handles subcategories like "Travel - Air"
function catColor(c: string): string {
  if (CAT_COLORS[c]) return CAT_COLORS[c];
  // Fuzzy match: "Travel - Air" -> Travel color, "Meals & Entmt" -> Meals color
  const cl = c.toLowerCase();
  if (cl.includes("travel")) return "#0891b2";
  if (cl.includes("meal") || cl.includes("food") || cl.includes("entertainment")) return "#16a34a";
  if (cl.includes("accommodation") || cl.includes("hotel") || cl.includes("lodg")) return "#0891b2";
  if (cl.includes("salary") || cl.includes("payroll")) return "#6366f1";
  if (cl.includes("rent") || cl.includes("lease")) return "#ef4444";
  if (cl.includes("tax")) return "#dc2626";
  if (cl.includes("software") || cl.includes("subscription")) return "#2563eb";
  if (cl.includes("office") || cl.includes("supply") || cl.includes("supplies")) return "#ca8a04";
  if (cl.includes("professional") || cl.includes("consulting") || cl.includes("fee")) return "#7c3aed";
  return "#94a3b8";
}

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

// ─── InsightsPanel ────────────────────────────────────────────────────────────
// Reads summary, anomalies, categorization from extraction_json (set by backend).
// Graphs are rendered from the already-extracted numeric fields.
// No browser API calls to Anthropic — everything is pre-computed server-side.

function ChartsPanel({ jobId }: { jobId: number }) {
  const { data, isError } = useQuery<ChartsResponse>({
    queryKey: ["charts", jobId],
    queryFn: () => extractApi.charts(jobId),
  });
  const empty = isError ? "Charts could not be loaded." : emptyReason(data);
  const banner = data ? reviewBanner(data) : null;
  return (
    <div className="card" style={{ padding: 16 }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)", marginBottom: 8 }}>Charts</div>
      {banner && <p role="status" style={{ fontSize: 11.5, color: "var(--amber)", marginBottom: 8 }}>{banner}</p>}
      {empty ? <p style={{ fontSize: 12, color: "var(--text3)" }}>{empty}</p> : (
        <>
          {data!.message && <p style={{ fontSize: 11.5, color: "var(--text3)", marginBottom: 8 }}>{data!.message}</p>}
          {Object.entries(data!.currencies).map(([cur, g]) => (
            <div key={cur} style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11.5, fontWeight: 600, color: "var(--text2)", marginBottom: 6 }}>{cur}</div>
              {g.by_category.length > 0 && (<><div style={{ fontSize: 11, color: "var(--text3)" }}>Spend by category</div>
                <BarChart data={bars(g.by_category)} height={90}/></>)}
              {g.by_month.length > 1 && (<><div style={{ fontSize: 11, color: "var(--text3)", marginTop: 6 }}>By month</div>
                <BarChart data={bars(g.by_month, 12)} height={90}/></>)}
              {g.top_items.length > 0 && (<><div style={{ fontSize: 11, color: "var(--text3)", marginTop: 6 }}>Largest items</div>
                <BarChart data={bars(g.top_items, 5)} height={70}/></>)}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function InsightsPanel({
  results, options, jobId,
}: {
  results: DocumentResult[]; options: OptionId[]; jobId?: number | null;
}) {
  if (!options.length) return null;

  // ── Flatten data from all results ─────────────────────────────────────────
  const allFields: Record<string, string> = {};
  const tableRows: Record<string, any>[] = [];
  const summaries: { text: string; notice?: string | null; label?: string }[] = [];
  const anomalies: { rule: string; severity: string; message: string }[] = [];
  const categories: { category: string; level: string; by: string; reasons?: string[] }[] = [];

  results.forEach(r => {
    const data = r.extracted_data ?? {};
    const inner = data.extracted_data ?? {};
    Object.entries(inner).forEach(([k, v]: any) => {
      if (!k.startsWith("_label_")) {
        allFields[k] = typeof v === "object" ? (v?.value ?? "") : String(v ?? "");
      }
    });
    (data.table_rows ?? []).forEach((row: any) => tableRows.push(row));
    // A2: categories live beside the rows (never inside them), with a level
    Object.values(data.categories ?? {}).forEach((entries: any) =>
      (entries ?? []).forEach((e: any) => categories.push(e)));
    // A4: facts-based summary; the prose only if it passed verification
    if (data.summary) summaries.push(typeof data.summary === "string"
      ? { text: data.summary, label: "generated, verify against the data" }
      : { text: data.summary.narrative || data.summary.text, notice: data.summary.notice,
          label: data.summary.label });
    // A3: rule-based anomalies (an older job may hold plain sentences)
    if (Array.isArray(data.anomalies)) data.anomalies.forEach((a: any) =>
      anomalies.push(typeof a === "string" ? { rule: "", severity: "low", message: a } : a));
  });

  // ── Categorization ────────────────────────────────────────────────────────
  const catCount: Record<string, number> = {};
  const catAmount: Record<string, number> = {};
  // Counts only: amounts per category come from the server's own
  // aggregation (one currency at a time), never from parsing text here.
  const catOpen = categories.filter(e => (e.reasons ?? []).length > 0 || e.by === "model").length;
  if (options.includes("categorize")) {
    categories.forEach(e => { catCount[e.category] = (catCount[e.category] ?? 0) + 1; });
  }
  const catPie = Object.entries(catCount).sort((a, b) => b[1] - a[1]).slice(0, 8)
    .map(([label, value]) => ({ label, value, color: catColor(label) }));
  const catBar = Object.entries(catAmount).filter(([, v]) => v > 0)
    .sort((a, b) => b[1] - a[1]).slice(0, 7)
    .map(([label, value]) => ({ label, value: Math.round(value * 100) / 100, color: catColor(label) }));

  // Numeric fields for graphs — exclude dates, years, IDs, counts
  const DATE_LIKE = /^\d{4}$|^\d{4}-\d{2}|^\d{2}\/\d{2}\/\d{4}$/;
  const EXCLUDE_LABELS = /date|period|year|month|day|id|no\.|number|emp|phone|zip|code/i;
  const numericFields = Object.entries(allFields)
    .filter(([k, v]) => {
      if (EXCLUDE_LABELS.test(k)) return false;
      if (DATE_LIKE.test(String(v).trim())) return false;
      const num = parseFloat(String(v).replace(/[^0-9.-]/g, ""));
      return !isNaN(num) && num > 0 && num < 1_000_000_000;
    })
    .map(([k, v]) => ({ label: k, value: parseFloat(String(v).replace(/[^0-9.-]/g, "")) }))
    .sort((a, b) => b.value - a.value).slice(0, 6);
  const fieldBar = numericFields.map((f, i) => ({ ...f, color: CHART_COLORS[i % CHART_COLORS.length] }));
  const fieldPie = numericFields.map((f, i) => ({ ...f, color: CHART_COLORS[i % CHART_COLORS.length] }));

  const summary = summaries[0] ?? null;
  const uniqueAnomalies = anomalies.filter((a, i) =>
    anomalies.findIndex(b => b.message === a.message) === i);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 14 }}>

      {/* AI Summary — read from extracted_data.summary (set by backend) */}
      {options.includes("summary") && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#f59e0b18",
              display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
              </svg>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>Summary</span>
            <span style={{ fontSize: 10.5, color: "var(--amber)", marginLeft: "auto" }}>
              {summary?.label ?? "generated, verify against the data"}
            </span>
          </div>
          <p style={{ fontSize: 12.5, color: "var(--text2)", lineHeight: 1.65 }}>
            {summary?.text || "No summary: the document produced no values to summarise."}
          </p>
          {summary?.notice && (
            <p role="status" style={{ fontSize: 11.5, color: "var(--amber)", marginTop: 6 }}>{summary.notice}</p>
          )}
        </div>
      )}

      {/* Categorization — reads Category field from table_rows */}
      {options.includes("categorize") && catPie.length > 0 && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#6366f118",
              display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2">
                <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
                <line x1="7" y1="7" x2="7.01" y2="7"/>
              </svg>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>Categorization</span>
            <span style={{ fontSize: 10, color: "var(--text3)", marginLeft: "auto" }}>
              {tableRows.length} items
            </span>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 14, alignItems: "center", marginBottom: 14 }}>
            <PieChart data={catPie} size={120}/>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {catPie.map((d, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 7, height: 7, borderRadius: 2, background: d.color, flexShrink: 0 }}/>
                  <span style={{ fontSize: 10.5, color: "var(--text2)", flex: 1,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {d.label}
                  </span>
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

      {/* Categorization no data */}
      {options.includes("categorize") && catPie.length === 0 && tableRows.length === 0 && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#6366f118",
              display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#6366f1" strokeWidth="2">
                <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
              </svg>
            </div>
            <div>
              <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>Categorization</span>
              <p style={{ fontSize: 11, color: "var(--text3)", marginTop: 2 }}>
                No table rows found. Categorization works with documents that have line items
                (bank statements, expense reports, invoices).
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Charts (A5): the server's exact aggregation, one currency at a time */}
      {options.includes("graphs") && jobId != null && <ChartsPanel jobId={jobId} />}

      {/* Anomaly Detection — reads from extracted_data.anomalies (set by backend) */}
      {options.includes("anomaly") && (
        <div className="card" style={{ padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
            <div style={{ width: 26, height: 26, borderRadius: 7, background: "#ef444418",
              display: "flex", alignItems: "center", justifyContent: "center" }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2">
                <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                <line x1="12" y1="9" x2="12" y2="13"/>
                <line x1="12" y1="17" x2="12.01" y2="17"/>
              </svg>
            </div>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text1)" }}>Anomaly Detection</span>
          </div>
          {uniqueAnomalies.length === 0 ? (
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                stroke="var(--green)" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
              <span style={{ fontSize: 12, color: "var(--text3)" }}>No anomalies detected</span>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {uniqueAnomalies.map((a, i) => (
                <div key={i} style={{ display: "flex", gap: 8, padding: "7px 10px",
                  background: "#ef444410", borderRadius: 6, border: "1px solid #ef444428" }}>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                    stroke="#ef4444" strokeWidth="2"
                    style={{ flexShrink: 0, marginTop: 2 }}>
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="8" x2="12" y2="12"/>
                    <line x1="12" y1="16" x2="12.01" y2="16"/>
                  </svg>
                  <span style={{ fontSize: 11.5, color: "var(--text2)", lineHeight: 1.5 }}>
                    <strong style={{ textTransform: "uppercase", fontSize: 10, marginRight: 6 }}>{a.severity}</strong>
                    {a.message}{a.rule ? <span style={{ color: "var(--text3)" }}> · {a.rule}</span> : null}
                  </span>
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
  const { user } = useAuthStore();
  const [selectedTemplate, setSelectedTemplate] = useState<ColumnTemplate | null>(null);
  const [templateSearch, setTemplateSearch] = useState("");
  const [activeTab, setActiveTab] = useState<SourceTab>("upload");
  // The files to upload, each with its own id and PDF password
  // (lib/uploadFiles.ts): in this page's memory only, sent with the upload,
  // wiped after it, never stored (the server does not keep them either).
  const [pending, setPending] = useState<PendingFile[]>([]);
  const files = filesOf(pending);
  const [folderPath, setFolderPath] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);
  const [activeJobId, setActiveJobId] = useState<number | null>(null);
  const [results, setResults] = useState<DocumentResult[]>([]);
  const [selectedOptions, setSelectedOptions] = useState<OptionId[]>([]);
  const [showNoTemplateModal, setShowNoTemplateModal] = useState(false);
  const [pageSelectModal, setPageSelectModal] = useState<{
    pageCount: number; selected: number[];
  } | null>(null);
  const prevStatus = useRef("");

  // /extract?job=<id> reopens a finished job for review (the History page
  // links here), so the review screen is reachable after the upload session.
  useEffect(() => {
    const j = new URLSearchParams(window.location.search).get("job");
    if (j && /^\d+$/.test(j)) setActiveJobId(Number(j));
  }, []);

  const { data: templates = [] } = useQuery<ColumnTemplate[]>({
    queryKey: ["templates"],
    queryFn: () => templatesApi.list(),
    staleTime: 0,
    refetchOnMount: true,
  });

  const { data: schemas = [] } = useQuery({
    queryKey: ["schemas"],
    queryFn: schemasApi.list,
  });

  const { data: jobStatus, isError: jobStatusError } = useQuery<JobStatus>({
    queryKey: ["job", activeJobId],
    queryFn: () => extractApi.getJob(activeJobId!),
    enabled: !!activeJobId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "processing" || s === "pending" ? 2000 : false;
    },
    staleTime: 0,
  });

  // "partial" is a finished job with real results for the documents that
  // worked, so it loads them exactly as "completed" does. The difference is
  // what the page then SAYS about the batch, not whether it fetches.
  const finishedWithResults = jobStatus?.status === "completed" || jobStatus?.status === "partial";
  // Overnight E1: the results are a QUERY (the key History uses), so a review
  // action's invalidation re-reads them; a one-off fetch into local state
  // kept the pre-edit copy and a saved correction reverted on screen.
  const resultsQ = useQuery<DocumentResult[]>({
    queryKey: ["job-results", activeJobId],
    queryFn: () => extractApi.getResults(activeJobId!),
    enabled: !!activeJobId && finishedWithResults,
    staleTime: 0,
  });
  useEffect(() => {
    if (resultsQ.data) { setResults(resultsQ.data); setIsExtracting(false); }
  }, [resultsQ.data]);
  if (finishedWithResults && prevStatus.current !== jobStatus!.status) {
    prevStatus.current = jobStatus!.status;
  }
  if (jobStatus?.status === "failed" && prevStatus.current !== "failed") {
    prevStatus.current = "failed";
    setIsExtracting(false);
  }
  if (jobStatus?.status) prevStatus.current = jobStatus.status;

  const onDrop = useCallback((accepted: File[]) => {
    setPending(prev => addFiles(prev, accepted));
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"], "image/*": [".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".heic", ".heif", ".gif", ".avif"] },
    multiple: true,
  });

  const clientId = schemas[0]?.client_id ?? "demo_001";
  // A demo account, as the SERVER computed it. Presentation only: /api/demo/*
  // is 404 for everyone else regardless of what this flag says.
  const isDemo = user?.is_demo === true;

  function toggleOption(id: OptionId) {
    // The demo shows all four options and turns none of them on. One guard
    // here covers both the card and its checkbox, because the checkbox is a
    // div inside the card and the card carries the only onClick. A toast id
    // means repeated clicking updates one toast instead of stacking four.
    if (isDemo) {
      toast(DEMO_OPTION_UNAVAILABLE, { id: "demo-option-unavailable" });
      return;
    }
    setSelectedOptions(prev => {
      const next = toggle(prev as OptionsId[], id as OptionsId) as OptionId[];
      saveRemembered(user?.id, next as OptionsId[]);
      return next;
    });
  }

  // A6: remember each user's choices (per browser; nothing stored server-side)
  useEffect(() => {
    if (user?.id != null && !isDemo) setSelectedOptions(loadRemembered(user.id) as OptionId[]);
  }, [user?.id, isDemo]);

  async function startExtract(templateId?: number, selectedPages?: number[]) {
    setIsExtracting(true);
    setResults([]);
    prevStatus.current = "";
    try {
      const pw = passwordsOf(pending);
      // Used once: wiped from the page as soon as the request is made.
      setPending(clearPasswords);
      const res = await extractApi.upload(files, clientId, templateId, selectedOptions, selectedPages, pw);
      setActiveJobId(res.job_id);
      toast.success(`Extraction started — ${res.total_files} file(s)`);
    } catch (e: any) {
      toast.error(apiErrorText(e, { isDemo, fallback: "Upload failed" }));
      setIsExtracting(false);
    }
  }

  /**
   * Extract one of the demo's shipped sample documents. Deliberately shaped
   * like `startExtract` above — same reset, same job id, same polling — because
   * the server runs the same pipeline; only the source of the bytes differs.
   */
  async function startExtractSample(filename: string) {
    setIsExtracting(true);
    setResults([]);
    prevStatus.current = "";
    try {
      const res = await extractApi.extractSampleDoc(
        filename, selectedTemplate?.id, selectedOptions);
      setActiveJobId(res.job_id);
      toast.success(`Extraction started — ${filename}`);
    } catch (e: any) {
      toast.error(apiErrorText(e, { isDemo, fallback: "Could not start extraction" }));
      setIsExtracting(false);
    }
  }

  async function handleExtract() {
    if (activeTab === "upload" && !files.length) return toast.error("Add files first");
    if (!selectedTemplate) {
      setShowNoTemplateModal(true);
      return;
    }
    // Check if single PDF has >1 page — show page selection modal
    const pdfs = files.filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 1) {
      try {
        const info = await extractApi.getPageCount([pdfs[0]]);
        const pageCount = info[0]?.page_count ?? 1;
        if (pageCount > 1) {
          setPageSelectModal({ pageCount, selected: Array.from({ length: pageCount }, (_, i) => i + 1) });
          return;
        }
      } catch {
        // ignore — proceed without page selection
      }
    }
    await startExtract(selectedTemplate.id);
  }

  function reset() {
    setPending([]); setResults([]); setActiveJobId(null);
    setSelectedTemplate(null); setTemplateSearch("");
    setActiveTab("upload"); setFolderPath("");
    if (window.location.search) window.history.replaceState(null, "", "/extract");
    prevStatus.current = ""; setIsExtracting(false);
  }

  const isRunning = jobStatus?.status === "processing" || jobStatus?.status === "pending";
  const isDone = jobStatus?.status === "completed" || jobStatus?.status === "partial";
  const isPartial = jobStatus?.status === "partial";
  const isFailed = jobStatus?.status === "failed";
  const isCancelled = jobStatus?.status === "cancelled";
  const [cancelling, setCancelling] = useState(false);
  // Run C, C2: the download holds only the template's fields unless asked.
  const handleCancel = async () => {
    if (!activeJobId || !confirm("Cancel this extraction? Files that already finished keep their results; the rest are listed as cancelled.")) return;
    setCancelling(true);
    setPending(clearPasswords);
    try { await extractApi.cancelJob(activeJobId); toast.success("Cancelling…"); }
    catch (e: any) { toast.error(e?.response?.data?.detail || "Cancel failed"); }
    finally { setCancelling(false); }
  };
  const hasResults = results.length > 0;
  // Run Q, UI1: the results are shown with the template the JOB ran with.
  // The picker chooses the template for the NEXT extraction only.
  const { template: jobTemplate, templateLoading } = useJobTemplate(jobStatus, templates);
  // Run Q Phase 3, UI3: the empty state previews the template of the job on
  // screen; the picker's choice is only for the NEXT extraction.
  const previewTemplate = activeJobId ? jobTemplate : selectedTemplate;
  const filteredTemplates = templateSearch.trim()
    ? templates.filter(t =>
        t.name.toLowerCase().includes(templateSearch.toLowerCase()) ||
        t.document_type.toLowerCase().includes(templateSearch.toLowerCase())
      )
    : templates;

  return (
    <AppLayout fitViewport={!activeJobId}>
      <style>{`
        .extract-heading { margin-bottom: 16px; flex-shrink: 0; }
        .extract-workspace { flex: 1; min-height: 0; display: grid; grid-template-rows: clamp(310px, 45vh, 366px) minmax(0, 1fr); gap: 16px; }
        .extract-top, .extract-bottom, .extract-progress { display: grid; gap: 16px; min-height: 0; }
        .extract-top { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        .extract-bottom, .extract-progress { grid-template-columns: minmax(220px, 1fr) minmax(0, 3fr); }
        .extract-panel { display: flex; flex-direction: column; padding: 14px; min-width: 0; min-height: 0; }
        .extract-progress { align-items: start; }
        .extract-progress-status { display: grid; gap: 8px; }
        .extract-document-source { flex: 1; min-height: 0; overflow: auto; }
        .extract-top .btn-lg { margin-top: 10px; flex-shrink: 0; }
        .extract-preview-name { margin: 4px 0 8px; font-weight: 600; overflow-wrap: anywhere; }
        .extract-preview-body { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
        .extract-preview-empty { display: flex; flex: 1; flex-direction: column; align-items: center; justify-content: center; gap: 12px; min-height: 110px; padding: 14px; text-align: center; color: var(--text2); }
        .extract-partial { margin-bottom: 10px; color: var(--amber); }
        @media (max-width: 840px) {
          .extract-workspace { grid-template-rows: auto auto; }
          .extract-top, .extract-bottom, .extract-progress { grid-template-columns: minmax(0, 1fr); }
          .extract-panel { max-height: 440px; }
        }

        .tpl-picker-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
        .tpl-list { display: flex; flex-direction: column; gap: 4px; min-height: 0; overflow-y: auto; }
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
        .progress-fill.partial { background: var(--amber); width: 100% !important; }
        .progress-fill.failed { background: var(--red); width: 100% !important; }
        .job-stats { display: flex; gap: 12px; flex-wrap: wrap; }
        .job-stat { font-size: 11px; color: var(--text3); }
        .job-stat b { font-weight: 600; }

        /* Options grid */
        .opt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; overflow: auto; }
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
        .opt-desc { font-size: 10.5px; color: var(--text2); line-height: 1.4; }

        @keyframes indeterminate {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(300%); }
        }
      `}</style>

      <header className="extract-heading">
        <h1 className="page-title">{isDone ? "Extraction results" : "Extract"}</h1>
        {jobModels(results) ? (
          <p className="page-sub">Extracted by {jobModels(results)}</p>
        ) : !activeJobId && (
          <p className="page-sub">Add documents and choose a template to guide extraction.</p>
        )}
      </header>

      {!activeJobId ? (
        <div className="extract-workspace">
          <div className="extract-top">
            {/* Documents uploader */}
            <div className="card extract-panel">
              <span className="label" style={{ display: "block", marginBottom: 10 }}>Documents</span>
              <div className="src-tabs">
                {/* Drive is closed for a demo account in the BACKEND (every
                    /api/drive route answers 403); the tab is hidden so nobody
                    clicks into a dead end. */}
                {(isDemo
                  ? (["upload","folder"] as SourceTab[])
                  : (["upload","folder","drive"] as SourceTab[])).map(tab => (
                  <div key={tab} className={`src-tab ${activeTab === tab ? "active" : ""}`} onClick={() => setActiveTab(tab)}
                    role="tab" tabIndex={0} aria-selected={activeTab === tab}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setActiveTab(tab); } }}>
                    {tab === "upload" && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>}
                    {tab === "folder" && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>}
                    {tab === "drive" && <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>}
                    {tab.charAt(0).toUpperCase() + tab.slice(1)}
                  </div>
                ))}
              </div>

              <div className="extract-document-source">
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
                      <p style={{ fontSize: 11, color: "var(--text4)" }}>PDF · PNG · JPG · TIFF · WEBP · HEIC · BMP · GIF — 50MB max</p>
                    </div>
                    {isDemo && (
                      <p style={{ fontSize: 11, color: "var(--text3)", marginTop: 8 }}>
                        Best results with digital PDFs. Try the sample documents first.
                      </p>
                    )}
                    {pending.map(({ id, file: f, password }) => (
                      <div key={id} className="file-item">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                        <span className="file-name">{f.name}</span>
                        <span className="file-size">{(f.size / 1024).toFixed(0)} KB</span>
                        {f.name.toLowerCase().endsWith(".pdf") && (
                          <input type="password" autoComplete="new-password" placeholder="PDF password"
                            name={`pdf-password-${id}`} data-lpignore="true" data-1p-ignore="true"
                            aria-label={`Password for ${f.name} (not saved)`}
                            title="Only if the PDF is password-protected. Used once to open it; not saved."
                            value={password}
                            onChange={e => { const v = e.target.value; setPending(p => setPassword(p, id, v)); }}
                            style={{ width: 110, fontSize: 11, padding: "2px 6px",
                                     border: "1px solid var(--border)", borderRadius: 4 }} />
                        )}
                        <button aria-label={`Remove ${f.name}`} onClick={() => setPending(p => removeFile(p, id))}
                          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 2 }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                      </div>
                    ))}
                  </>
                )}

                {activeTab === "folder" && (
                  <div>
                    <input className="input" placeholder="C:\Documents\invoices"
                      value={folderPath} onChange={e => setFolderPath(e.target.value)}/>
                    <p style={{ fontSize: 11, color: "var(--text4)", marginTop: 6 }}>Local folder — all PDFs and images inside will be uploaded</p>
                  </div>
                )}

                {activeTab === "drive" && (
                  <DriveTab selectedTemplate={selectedTemplate} clientId={clientId}
                    onJobStarted={(jobId) => { setActiveJobId(jobId); setIsExtracting(true); }}/>
                )}
                <SampleDocsPanel
                  enabled={isDemo}
                  busy={isExtracting || isRunning}
                  onUse={startExtractSample}
                />
              </div>
              {/* Extract button */}
              {activeTab !== "drive" && (
                <button className="btn btn-primary btn-full btn-lg" onClick={handleExtract}
                  disabled={isExtracting || (activeTab === "upload" && !files.length)}>
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
            </div>
            {/* Additional options */}
            <div className="card extract-panel">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                <span className="label">Additional options</span>
                {selectedOptions.length > 0 && (
                  <button style={{ fontSize: 10, color: "var(--text3)", background: "none", border: "none", cursor: "pointer" }}
                    onClick={() => { setSelectedOptions([]); saveRemembered(user?.id, []); }}>Clear</button>
                )}
              </div>
              <div className="opt-grid" role="group" aria-label="Additional options">
                {EXTRA_OPTIONS.map(opt => {
                  const st = optionState(opt.id as OptionsId, selectedOptions as OptionsId[], { isDemo });
                  const info = OPTION_INFO[opt.id as OptionsId];
                  return (
                  <label key={opt.id} className={`opt-card ${selectedOptions.includes(opt.id) ? "on" : ""}`}
                    style={st.disabled && !isDemo ? { opacity: 0.6, cursor: "not-allowed" } : undefined}
                    title={[info.help, info.cost, st.why].filter(Boolean).join(" ")}>
                    <input type="checkbox" className="sr-only" checked={selectedOptions.includes(opt.id)}
                      disabled={st.disabled && !isDemo}
                      aria-describedby={`opt-help-${opt.id}`}
                      onChange={() => toggleOption(opt.id)} />
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
                    <p className="opt-desc">
                      {opt.desc}
                      <span style={{ display: "block", color: "var(--text3)" }}>{opt.cost}</span>
                      {st.why && !isDemo && <span style={{ display: "block", color: "var(--amber)" }}>Turn on Summary first.</span>}
                    </p>
                    <span className="sr-only" id={`opt-help-${opt.id}`}>{info.help} {info.cost} {st.why}</span>
                  </label>
                  );
                })}
              </div>
            </div>
          </div>
          <div className="extract-bottom">
            {/* Template picker */}
            <div className="card extract-panel">
              <div className="tpl-picker-header">
                <span className="label">Template selector</span>
                <Link href="/templates" className="btn btn-ghost btn-sm" style={{ fontSize: 11 }}>Manage</Link>
              </div>
              {templates.length === 0 ? (
                <div className="tpl-none">No templates — <Link href="/templates/new" style={{ color: "var(--accent)" }}>create one</Link></div>
              ) : (
                <>
                    <div style={{ position: "relative", marginBottom: 8 }}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="2"
                        style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }}>
                        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                      </svg>
                      <input
                        type="text"
                        placeholder="Search templates…" aria-label="Search templates"
                        value={templateSearch}
                        onChange={e => setTemplateSearch(e.target.value)}
                        style={{
                          width: "100%", boxSizing: "border-box",
                          padding: "6px 26px 6px 26px",
                          border: "1px solid var(--border)", borderRadius: 6,
                          background: "var(--surface2)", color: "var(--text1)",
                          fontSize: 11.5, outline: "none",
                        }}
                      />
                      {templateSearch && (
                        <button
                          aria-label="Clear template search" onClick={() => setTemplateSearch("")}
                          style={{ position: "absolute", right: 7, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", color: "var(--text3)", padding: 2 }}
                        >
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                      )}
                    </div>
                  <div className="tpl-list">
                    {filteredTemplates.length === 0 ? (
                      <div style={{ padding: "12px 0", textAlign: "center", fontSize: 11.5, color: "var(--text4)" }}>
                        No templates match "{templateSearch}"
                      </div>
                    ) : filteredTemplates.map(t => (
                      <div key={t.id} className={`tpl-row ${selectedTemplate?.id === t.id ? "sel" : ""}`}
                        role="button" tabIndex={0} aria-pressed={selectedTemplate?.id === t.id}
                        onClick={() => setSelectedTemplate(selectedTemplate?.id === t.id ? null : t)}
                        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedTemplate(selectedTemplate?.id === t.id ? null : t); } }}>
                        <div className="tpl-dot"/>
                        <span className="tpl-name">{t.name}</span>
                        <span className="tpl-type">{t.document_type}</span>
                      </div>
                    ))}
                  </div>
                </>
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
            <section className="card extract-panel" aria-label="Template layout preview">
              <h2 className="label">Template layout preview</h2>
              {previewTemplate ? (
                <>
                  <p className="extract-preview-name">{previewTemplate.name}</p>
                  <div className="extract-preview-body"><TemplatePreview template={previewTemplate} /></div>
                </>
              ) : (
                <p className="extract-preview-empty">Choose a template to preview its spreadsheet layout. You can also extract without one.</p>
              )}
            </section>
          </div>
        </div>
      ) : finishedWithResults && jobStatus ? (
        <JobResultsLayout key={jobStatus.id} job={jobStatus} template={jobTemplate} templateLoading={templateLoading}
          documentCount={results.length} onNew={reset}>
          {jobStatus.status === "partial" && jobStatus.error_message && (
            <p className="extract-partial">{jobErrorText(jobStatus.error_message, isDemo)}</p>
          )}
          {hasResults ? (
            <>
              <ResultsGrid results={results} jobId={jobStatus.id} template={jobTemplate} />
              {selectedOptions.length > 0 && <InsightsPanel results={results} options={selectedOptions} jobId={activeJobId} />}
            </>
          ) : (
            <div className="card extract-panel">
              <p>{resultsQ.isError ? "Results could not be loaded." : resultsQ.isPending ? "Loading results…" : "No documents to review."}</p>
              {previewTemplate && <div className="extract-preview-body"><TemplatePreview template={previewTemplate} /></div>}
            </div>
          )}
        </JobResultsLayout>
      ) : (
        <div className="extract-progress">
          <div className="extract-progress-status">
            <section className="card job-result-info">
              <h2 className="label">Template used</h2>
              <p>{templateUsedLabel(jobStatus, jobTemplate, templateLoading)}</p>
            </section>
            <div className="card" style={{ padding: 14 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                {isRunning && <svg className="animate-spin" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>}
                {isDone && !isPartial && <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>}
                {isPartial && <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" strokeWidth="2"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>}
                {isFailed && <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--red)" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>}
                <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text1)" }}>
                  {isRunning ? "Extracting…"
                    : isPartial ? `${jobStatus?.failed} of ${jobStatus?.total_docs} documents failed`
                    : isDone ? `Extraction complete · ${plainStatus(jobStatus ?? {})}`
                    : isCancelled ? "Extraction cancelled"
                    : isFailed ? "Extraction failed" : "Loading status…"}
                </span>
                {isRunning && jobStatus && mayCancel(user, jobStatus) && (
                  <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }}
                          disabled={cancelling} onClick={handleCancel}>
                    {cancelling ? "Cancelling…" : "Cancel"}
                  </button>
                )}
              </div>
              {(isCancelled || isFailed) && (jobStatus?.status_reason || jobStatus?.progress_message) && (
                <p style={{ fontSize: 11, color: "var(--text2)", marginBottom: 6 }}>
                  {[jobStatus?.status_reason, isCancelled ? jobStatus?.progress_message : null].filter(Boolean).join(" — ")}
                </p>
              )}
              <div className="progress-bar">
                <div className={`progress-fill ${isRunning ? "running" : isPartial ? "partial" : isDone ? "done" : "failed"}`}/>
              </div>
              {jobStatus && (
                <div className="job-stats">
                  <span className="job-stat"><b>{jobStatus.total_docs}</b> docs</span>
                  {jobStatus.successful > 0 && <span className="job-stat" style={{ color: "var(--green)" }}><b>{jobStatus.successful}</b> ok</span>}
                  {jobStatus.failed > 0 && <span className="job-stat" style={{ color: "var(--red)" }}><b>{jobStatus.failed}</b> failed</span>}
                  {(jobStatus.needs_attention ?? 0) > 0 && (
                    <span className="job-stat" style={{ color: "var(--red)" }}
                          title="The page holds something the extraction does not (a table, an amount, a page). Settle each reason in review.">
                      <b>{jobStatus.needs_attention}</b> need attention
                    </span>
                  )}
                  {jobStatus.pages_total != null && (
                    <span className="job-stat">pages <b>{jobStatus.pages_processed}</b> of {jobStatus.pages_total}</span>
                  )}
                  {isDone && <span className="job-stat"><b>{(jobStatus.total_time_sec ?? 0).toFixed(1)}s</b></span>}
                </div>
              )}
              {(isFailed || isPartial) && jobStatus?.error_message && (
                <p style={{ fontSize: 11, color: isPartial ? "var(--amber)" : "var(--red)", marginTop: 8 }}>
                  {jobErrorText(jobStatus.error_message, isDemo)}
                </p>
              )}
            </div>
          </div>
          <div className="card">
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
            ) : isFailed ? (
              /* ── Job failed — clear error panel ── */
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: 380, padding: 40, gap: 16 }}>
                <div style={{ width: 52, height: 52, borderRadius: 14, background: "#ef444418", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--red,#ef4444)" strokeWidth="1.5">
                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                    <line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                  </svg>
                </div>
                <div style={{ textAlign: "center" }}>
                  <p style={{ fontSize: 15, fontWeight: 600, color: "var(--text1)", marginBottom: 6 }}>Extraction failed</p>
                  <p style={{ fontSize: 12, color: "var(--text3)", maxWidth: 300 }}>
                    {jobStatus?.failed > 0
                      ? `${jobStatus.failed} of ${jobStatus.total_docs} document${jobStatus.total_docs !== 1 ? "s" : ""} could not be processed.`
                      : "The job encountered an error and could not complete."}
                  </p>
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%", maxWidth: 420 }}>
                  {/* The DOCUMENTS' own reason, when the backend gave one.
                      It always had one — `_fail` writes it, the job thread
                      stores it, the API returns it — and nothing rendered
                      it, so "This template has no slots to fill…" showed up
                      here as four guesses about password-protected PDFs.
                      The guesses now appear only when there is no real
                      message to show. */}
                  {jobStatus?.error_message ? (
                    <div style={{ padding: "12px 14px", background: "var(--surface2)", borderRadius: 8, fontSize: 12, color: "var(--text2)", lineHeight: 1.55, textAlign: "left" }}>
                      <p style={{ fontWeight: 600, color: "var(--text1)", marginBottom: 4, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>What went wrong</p>
                      {jobErrorText(jobStatus.error_message, isDemo)}
                    </div>
                  ) : (
                  <div style={{ padding: "10px 14px", background: "var(--surface2)", borderRadius: 8, fontSize: 11, color: "var(--text3)" }}>
                    <p style={{ fontWeight: 600, color: "var(--text2)", marginBottom: 4 }}>Common causes:</p>
                    <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 3 }}>
                      <li>Template not found or corrupted — try re-saving it</li>
                      <li>PDF is password-protected or image-only (scanned)</li>
                      <li>File type not supported</li>
                      <li>AI service temporarily unavailable — retry in a moment</li>
                    </ul>
                  </div>
                  )}
                  <button
                    className="btn btn-secondary"
                    style={{ width: "100%" }}
                    onClick={() => {
                      setActiveJobId(null);
                      setResults([]);
                    }}
                  >
                    Try again
                  </button>
                </div>
              </div>
            ) : (
              <div className="extract-preview-empty">
                <p>{isCancelled ? "Extraction cancelled" : jobStatusError ? "The job could not be loaded." : "Loading extraction…"}</p>
                {(isCancelled || jobStatusError) && <button className="btn btn-secondary" onClick={reset}>Back to Extract</button>}
              </div>
            )}
          </div>
        </div>
      )}
      {/* Page selection modal (single PDF with >1 page) */}
      {pageSelectModal && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
        }} onClick={() => setPageSelectModal(null)}>
          <div style={{
            background: "var(--surface)", borderRadius: 12, padding: "24px",
            maxWidth: 460, width: "92%", maxHeight: "80vh", display: "flex",
            flexDirection: "column", gap: 16,
            boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
          }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: "#4f46e518",
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#4f46e5" strokeWidth="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                  <polyline points="14 2 14 8 20 8"/>
                  <line x1="9" y1="13" x2="15" y2="13"/>
                </svg>
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text1)" }}>Select pages to extract</div>
                <div style={{ fontSize: 12, color: "var(--text3)" }}>
                  {pageSelectModal.pageCount} pages detected — choose which to process
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={() => setPageSelectModal(m => m && ({ ...m, selected: Array.from({ length: m.pageCount }, (_, i) => i + 1) }))}
                style={{ fontSize: 11.5, padding: "4px 10px", borderRadius: 5, border: "1px solid var(--border)", background: "transparent", color: "var(--text2)", cursor: "pointer" }}>
                Select All
              </button>
              <button onClick={() => setPageSelectModal(m => m && ({ ...m, selected: [] }))}
                style={{ fontSize: 11.5, padding: "4px 10px", borderRadius: 5, border: "1px solid var(--border)", background: "transparent", color: "var(--text2)", cursor: "pointer" }}>
                Clear All
              </button>
            </div>

            <div style={{ overflowY: "auto", maxHeight: 300, display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(80px, 1fr))", gap: 6 }}>
              {Array.from({ length: pageSelectModal.pageCount }, (_, i) => i + 1).map(pg => {
                const checked = pageSelectModal.selected.includes(pg);
                return (
                  <label key={pg} style={{
                    display: "flex", alignItems: "center", gap: 6, padding: "6px 10px",
                    borderRadius: 6, border: `1px solid ${checked ? "var(--accent)" : "var(--border)"}`,
                    background: checked ? "rgba(79,70,229,0.06)" : "transparent",
                    cursor: "pointer", fontSize: 12.5, color: checked ? "var(--accent)" : "var(--text2)",
                    fontWeight: checked ? 600 : 400,
                  }}>
                    <input type="checkbox" checked={checked} style={{ display: "none" }}
                      onChange={() => setPageSelectModal(m => {
                        if (!m) return m;
                        const next = m.selected.includes(pg)
                          ? m.selected.filter(p => p !== pg)
                          : [...m.selected, pg].sort((a, b) => a - b);
                        return { ...m, selected: next };
                      })} />
                    <div style={{ width: 12, height: 12, borderRadius: 3, border: `2px solid ${checked ? "var(--accent)" : "#d1d5db"}`, background: checked ? "var(--accent)" : "transparent", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                      {checked && <svg width="8" height="8" viewBox="0 0 12 12" fill="none"><polyline points="2,6 5,9 10,3" stroke="#fff" strokeWidth="2" strokeLinecap="round"/></svg>}
                    </div>
                    Page {pg}
                  </label>
                );
              })}
            </div>

            <div style={{ fontSize: 12, color: "var(--text3)" }}>
              {pageSelectModal.selected.length} of {pageSelectModal.pageCount} pages selected
            </div>

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => setPageSelectModal(null)}
                style={{ padding: "7px 16px", borderRadius: 7, border: "1px solid var(--border)", background: "transparent", color: "var(--text2)", fontSize: 13, cursor: "pointer", fontWeight: 500 }}>
                Cancel
              </button>
              <button
                disabled={pageSelectModal.selected.length === 0}
                onClick={() => {
                  const pages = pageSelectModal.selected;
                  setPageSelectModal(null);
                  startExtract(selectedTemplate?.id, pages.length < pageSelectModal.pageCount ? pages : undefined);
                }}
                style={{ padding: "7px 18px", borderRadius: 7, border: "none", background: pageSelectModal.selected.length === 0 ? "#e5e7eb" : "var(--accent)", color: pageSelectModal.selected.length === 0 ? "#9ca3af" : "#fff", fontSize: 13, cursor: pageSelectModal.selected.length === 0 ? "not-allowed" : "pointer", fontWeight: 600 }}>
                Extract {pageSelectModal.selected.length > 0 ? `(${pageSelectModal.selected.length} pages)` : ""}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* No-template confirmation modal */}
      {showNoTemplateModal && (
        <div style={{
          position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
          display: "flex", alignItems: "center", justifyContent: "center",
          zIndex: 1000,
        }} onClick={() => setShowNoTemplateModal(false)}>
          <div style={{
            background: "var(--surface)", borderRadius: 12, padding: "28px 28px 24px",
            maxWidth: 420, width: "90%", boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
          }} onClick={e => e.stopPropagation()}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 16 }}>
              <div style={{
                width: 36, height: 36, borderRadius: 9, background: "#f59e0b18",
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
                  <line x1="12" y1="9" x2="12" y2="13"/>
                  <line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
              </div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--text1)", marginBottom: 6 }}>
                  No template selected
                </div>
                <p style={{ fontSize: 13, color: "var(--text2)", lineHeight: 1.6, margin: 0 }}>
                  The AI will extract all content from this document in a
                  structured format.
                </p>
              </div>
            </div>
            <p style={{ fontSize: 12.5, color: "var(--text3)", marginBottom: 20, paddingLeft: 48 }}>
              For best results, select a template that matches your document type.
              Continue without one?
            </p>
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                onClick={() => setShowNoTemplateModal(false)}
                style={{
                  padding: "7px 16px", borderRadius: 7, border: "1px solid var(--border)",
                  background: "transparent", color: "var(--text2)", fontSize: 13,
                  cursor: "pointer", fontWeight: 500,
                }}>
                Cancel
              </button>
              <button
                onClick={() => { setShowNoTemplateModal(false); startExtract(undefined); }}
                style={{
                  padding: "7px 18px", borderRadius: 7, border: "none",
                  background: "var(--accent)", color: "#fff", fontSize: 13,
                  cursor: "pointer", fontWeight: 600,
                }}>
                Continue
              </button>
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
