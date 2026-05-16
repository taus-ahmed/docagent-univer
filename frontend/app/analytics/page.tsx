"use client";

import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { extractApi, type JobStatus, type DocumentResult } from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────
// Gemini 2.5 Flash Lite blended rate
const COST_PER_1K_TOKENS = 0.00015; // $0.15 per 1M = $0.00015 per 1K

function costOf(tokens: number) {
  return (tokens / 1000) * COST_PER_1K_TOKENS;
}

function fmt$(n: number) {
  if (n < 0.01) return `$${(n * 100).toFixed(3)}¢`;
  return `$${n.toFixed(n < 1 ? 4 : 2)}`;
}

function fmtNum(n: number) {
  return n.toLocaleString("en-US");
}

// ── Mini bar chart ─────────────────────────────────────────────────────────────
function MiniBar({ data, color = "var(--accent)" }: {
  data: { label: string; value: number }[];
  color?: string;
}) {
  if (!data.length) return null;
  const max = Math.max(...data.map(d => d.value), 1);
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 60 }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
          <div style={{
            width: "100%", height: Math.max(2, (d.value / max) * 52),
            background: color, borderRadius: "3px 3px 0 0", opacity: 0.85,
            transition: "height 0.3s",
          }} />
          <span style={{ fontSize: 9, color: "var(--text4)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>
            {d.label}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color, icon }: {
  label: string; value: string; sub?: string; color?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 10, padding: "16px 18px",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        {icon && <span style={{ color: color ?? "var(--accent)" }}>{icon}</span>}
        <span style={{ fontSize: 11, color: "var(--text3)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 26, fontWeight: 700, color: color ?? "var(--text1)", lineHeight: 1 }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <h2 style={{ fontSize: 13, fontWeight: 700, color: "var(--text2)", marginBottom: 14,
        textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {title}
      </h2>
      {children}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AnalyticsPage() {
  const [devMode, setDevMode] = useState(true); // toggle: dev sees tokens/cost, client sees usage only

  const { data: jobs = [], isLoading } = useQuery<JobStatus[]>({
    queryKey: ["jobs-analytics"],
    queryFn: () => extractApi.listJobs({ limit: 200 }),
    staleTime: 30_000,
  });

  // Fetch results for last 20 completed jobs to get token data
  const recentJobs = jobs.filter(j => j.status === "completed").slice(0, 20);
  const { data: allResults = [] } = useQuery<DocumentResult[]>({
    queryKey: ["results-analytics", recentJobs.map(j => j.id).join(",")],
    queryFn: async () => {
      const batches = await Promise.all(
        recentJobs.slice(0, 10).map(j => extractApi.getResults(j.id).catch(() => []))
      );
      return batches.flat();
    },
    enabled: recentJobs.length > 0,
    staleTime: 60_000,
  });

  // ── Computed stats ────────────────────────────────────────────────────────
  const stats = useMemo(() => {
    const completed  = jobs.filter(j => j.status === "completed");
    const failed     = jobs.filter(j => j.status === "failed");
    const totalDocs  = completed.reduce((s, j) => s + j.total_docs, 0);
    const totalOk    = completed.reduce((s, j) => s + j.successful, 0);
    const totalFail  = jobs.reduce((s, j) => s + j.failed, 0);
    const totalReview = completed.reduce((s, j) => s + j.needs_review, 0);
    const totalTime  = completed.reduce((s, j) => s + (j.total_time_sec || 0), 0);
    const avgTime    = completed.length ? totalTime / completed.length : 0;

    // Token / cost from document results
    const totalTokens = allResults.reduce((s, d) => s + (d.tokens_used || 0), 0);
    const totalCost   = costOf(totalTokens);
    const avgTokens   = allResults.length ? totalTokens / allResults.length : 0;
    const avgCost     = costOf(avgTokens);

    // Confidence breakdown
    const confCounts = { high: 0, medium: 0, low: 0 };
    allResults.forEach(d => {
      if (d.overall_confidence) confCounts[d.overall_confidence]++;
    });

    // Doc types breakdown
    const docTypeCounts: Record<string, number> = {};
    allResults.forEach(d => {
      const t = d.document_type || "unknown";
      docTypeCounts[t] = (docTypeCounts[t] || 0) + 1;
    });

    // Success rate
    const successRate = totalDocs > 0 ? Math.round((totalOk / totalDocs) * 100) : 0;

    // Last 14 days activity
    const now = Date.now();
    const dayMs = 86_400_000;
    const days = Array.from({ length: 14 }, (_, i) => {
      const d = new Date(now - (13 - i) * dayMs);
      return {
        label: d.toLocaleDateString("en-US", { month: "numeric", day: "numeric" }),
        date: d.toDateString(),
        value: 0,
      };
    });
    completed.forEach(j => {
      if (!j.created_at) return;
      const d = new Date(j.created_at).toDateString();
      const slot = days.find(s => s.date === d);
      if (slot) slot.value += j.total_docs;
    });

    // Model usage
    const modelCounts: Record<string, number> = {};
    allResults.forEach(d => {
      const m = d.model_used || "unknown";
      modelCounts[m] = (modelCounts[m] || 0) + 1;
    });

    return {
      totalJobs: jobs.length, completed: completed.length,
      failed: failed.length, totalDocs, totalOk, totalFail,
      totalReview, successRate, avgTime,
      totalTokens, totalCost, avgTokens, avgCost,
      confCounts, docTypeCounts, days, modelCounts,
    };
  }, [jobs, allResults]);

  if (isLoading) {
    return (
      <AppLayout>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: 40 }}>
          <svg className="animate-spin" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
          <span style={{ color: "var(--text3)", fontSize: 14 }}>Loading analytics…</span>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div style={{ marginBottom: 24, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="page-title">Analytics</h1>
          <p className="page-sub">Extraction performance and usage overview</p>
        </div>
        {/* Dev / Client toggle */}
        <button
          onClick={() => setDevMode(p => !p)}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "7px 14px", borderRadius: 8, border: "1px solid var(--border)",
            background: devMode ? "var(--accent-dim)" : "var(--surface2)",
            color: devMode ? "var(--accent)" : "var(--text3)",
            fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            {devMode
              ? <><path d="M2 13.5V19a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-5.5"/><path d="M2 10.5V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5.5"/><line x1="12" y1="12" x2="12" y2="12.01"/></>
              : <><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></>
            }
          </svg>
          {devMode ? "Dev view" : "Client view"}
        </button>
      </div>

      {jobs.length === 0 ? (
        <div className="card" style={{ padding: "48px 32px", textAlign: "center" }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5" style={{ margin: "0 auto 12px", display: "block" }}>
            <line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/>
            <line x1="6" y1="20" x2="6" y2="14"/><line x1="2" y1="20" x2="22" y2="20"/>
          </svg>
          <p style={{ fontWeight: 500, color: "var(--text1)" }}>No data yet</p>
          <p style={{ fontSize: 12, color: "var(--text3)", marginTop: 4 }}>
            Run your first extraction to see analytics here
          </p>
        </div>
      ) : (
        <>
          {/* ── Overview stats ── */}
          <Section title="Overview">
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
              <StatCard
                label="Total jobs"
                value={fmtNum(stats.totalJobs)}
                sub={`${stats.completed} completed · ${stats.failed} failed`}
                icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>}
              />
              <StatCard
                label="Documents"
                value={fmtNum(stats.totalDocs)}
                sub={`${stats.totalOk} ok · ${stats.totalFail} failed`}
                color="var(--accent)"
                icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>}
              />
              <StatCard
                label="Success rate"
                value={`${stats.successRate}%`}
                sub={`${stats.totalReview} need review`}
                color={stats.successRate >= 90 ? "var(--green)" : stats.successRate >= 70 ? "var(--amber)" : "var(--red)"}
                icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="20 6 9 17 4 12"/></svg>}
              />
              <StatCard
                label="Avg time/job"
                value={`${stats.avgTime.toFixed(1)}s`}
                sub="processing time"
                icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>}
              />
            </div>
          </Section>

          {/* ── Dev-only: Token & cost stats ── */}
          {devMode && (
            <Section title="Token usage & cost (dev only — not shown to clients)">
              <div style={{
                padding: "10px 14px", marginBottom: 14,
                background: "var(--accent-dim)", borderRadius: 8,
                fontSize: 11, color: "var(--accent)", fontWeight: 500,
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                </svg>
                This section is only visible in Dev view. Switch to Client view to see what clients see.
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
                <StatCard
                  label="Total tokens"
                  value={stats.totalTokens > 1000 ? `${(stats.totalTokens/1000).toFixed(1)}k` : fmtNum(stats.totalTokens)}
                  sub={`across ${allResults.length} documents`}
                  color="var(--accent)"
                  icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>}
                />
                <StatCard
                  label="Total AI cost"
                  value={fmt$(stats.totalCost)}
                  sub="gemini-2.5-flash-lite"
                  color="var(--green)"
                  icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>}
                />
                <StatCard
                  label="Avg tokens/doc"
                  value={fmtNum(Math.round(stats.avgTokens))}
                  sub={`≈ ${fmt$(stats.avgCost)} per doc`}
                  icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>}
                />
                <StatCard
                  label="Cost per 1000 docs"
                  value={fmt$(costOf(stats.avgTokens) * 1000)}
                  sub="projected"
                  color="var(--amber)"
                  icon={<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 20h.01M7 20v-4"/><path d="M12 20v-8"/><path d="M17 20V8"/><path d="M22 4v16"/></svg>}
                />
              </div>

              {/* Model usage */}
              {Object.keys(stats.modelCounts).length > 0 && (
                <div style={{ marginTop: 14, padding: "12px 14px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10 }}>
                  <p style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.04em" }}>Model usage</p>
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {Object.entries(stats.modelCounts).map(([model, count]) => (
                      <div key={model} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <span style={{ fontSize: 12, color: "var(--text1)", fontFamily: "monospace", flex: 1 }}>{model}</span>
                        <div style={{ flex: 2, height: 6, background: "var(--surface2)", borderRadius: 3, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${(count / allResults.length) * 100}%`, background: "var(--accent)", borderRadius: 3 }} />
                        </div>
                        <span style={{ fontSize: 11, color: "var(--text3)", width: 60, textAlign: "right" }}>{count} docs</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Section>
          )}

          {/* ── Activity chart ── */}
          <Section title="Activity — last 14 days">
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "16px 18px" }}>
              <MiniBar data={stats.days} color="var(--accent)" />
              <p style={{ fontSize: 10, color: "var(--text4)", marginTop: 8 }}>
                Documents processed per day
              </p>
            </div>
          </Section>

          {/* ── Two column: confidence + doc types ── */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 28 }}>
            {/* Confidence breakdown */}
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "16px 18px" }}>
              <p style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Confidence breakdown
              </p>
              {allResults.length === 0 ? (
                <p style={{ fontSize: 12, color: "var(--text4)" }}>No data yet</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {(["high", "medium", "low"] as const).map(level => {
                    const count = stats.confCounts[level];
                    const pct = allResults.length ? Math.round((count / allResults.length) * 100) : 0;
                    const color = level === "high" ? "var(--green)" : level === "medium" ? "var(--amber)" : "var(--red)";
                    return (
                      <div key={level}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                          <span style={{ fontSize: 12, color, fontWeight: 600, textTransform: "capitalize" }}>{level}</span>
                          <span style={{ fontSize: 11, color: "var(--text3)" }}>{count} ({pct}%)</span>
                        </div>
                        <div style={{ height: 6, background: "var(--surface2)", borderRadius: 3, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 3, transition: "width 0.4s" }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Document types */}
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, padding: "16px 18px" }}>
              <p style={{ fontSize: 11, fontWeight: 600, color: "var(--text3)", marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.04em" }}>
                Document types
              </p>
              {Object.keys(stats.docTypeCounts).length === 0 ? (
                <p style={{ fontSize: 12, color: "var(--text4)" }}>No data yet</p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                  {Object.entries(stats.docTypeCounts)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 6)
                    .map(([type, count], i) => {
                      const colors = ["var(--accent)", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"];
                      const total = Object.values(stats.docTypeCounts).reduce((s, v) => s + v, 0);
                      const pct = Math.round((count / total) * 100);
                      return (
                        <div key={type} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ width: 8, height: 8, borderRadius: "50%", background: colors[i], flexShrink: 0 }} />
                          <span style={{ fontSize: 12, color: "var(--text1)", flex: 1, textTransform: "capitalize" }}>
                            {type.replace(/_/g, " ")}
                          </span>
                          <span style={{ fontSize: 11, color: "var(--text3)" }}>{count}</span>
                          <span style={{ fontSize: 10, color: "var(--text4)", width: 32, textAlign: "right" }}>{pct}%</span>
                        </div>
                      );
                    })}
                </div>
              )}
            </div>
          </div>

          {/* ── Recent jobs table ── */}
          <Section title="Recent jobs">
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ borderBottom: "1px solid var(--border)", background: "var(--surface2)" }}>
                    <th style={{ padding: "9px 14px", textAlign: "left", fontWeight: 600, color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>Job</th>
                    <th style={{ padding: "9px 14px", textAlign: "left", fontWeight: 600, color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>Status</th>
                    <th style={{ padding: "9px 14px", textAlign: "right", fontWeight: 600, color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>Docs</th>
                    <th style={{ padding: "9px 14px", textAlign: "right", fontWeight: 600, color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>Time</th>
                    {devMode && <th style={{ padding: "9px 14px", textAlign: "right", fontWeight: 600, color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>Tokens</th>}
                    {devMode && <th style={{ padding: "9px 14px", textAlign: "right", fontWeight: 600, color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>Cost</th>}
                    <th style={{ padding: "9px 14px", textAlign: "left", fontWeight: 600, color: "var(--text3)", fontSize: 10, textTransform: "uppercase", letterSpacing: "0.04em" }}>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.slice(0, 15).map((job, i) => {
                    const jobResults = allResults.filter(r => r.job_id === job.id);
                    const jobTokens  = jobResults.reduce((s, r) => s + (r.tokens_used || 0), 0);
                    const jobCost    = costOf(jobTokens);
                    const statusColor = job.status === "completed" ? "var(--green)" : job.status === "failed" ? "var(--red)" : "var(--amber)";
                    return (
                      <tr key={job.id} style={{ borderBottom: "1px solid var(--border)", background: i % 2 === 0 ? "transparent" : "var(--surface2)" }}>
                        <td style={{ padding: "9px 14px", color: "var(--text1)", fontWeight: 500 }}>#{job.id}</td>
                        <td style={{ padding: "9px 14px" }}>
                          <span style={{ fontSize: 11, fontWeight: 600, color: statusColor, textTransform: "capitalize" }}>
                            {job.status}
                          </span>
                        </td>
                        <td style={{ padding: "9px 14px", textAlign: "right", color: "var(--text2)" }}>
                          {job.total_docs}
                          {job.failed > 0 && <span style={{ color: "var(--red)", marginLeft: 4 }}>({job.failed}✗)</span>}
                        </td>
                        <td style={{ padding: "9px 14px", textAlign: "right", color: "var(--text3)", fontVariantNumeric: "tabular-nums" }}>
                          {job.total_time_sec > 0 ? `${job.total_time_sec.toFixed(1)}s` : "—"}
                        </td>
                        {devMode && (
                          <td style={{ padding: "9px 14px", textAlign: "right", color: "var(--text3)", fontVariantNumeric: "tabular-nums" }}>
                            {jobTokens > 0 ? `${(jobTokens / 1000).toFixed(1)}k` : "—"}
                          </td>
                        )}
                        {devMode && (
                          <td style={{ padding: "9px 14px", textAlign: "right", color: jobCost > 0 ? "var(--green)" : "var(--text4)", fontVariantNumeric: "tabular-nums" }}>
                            {jobCost > 0 ? fmt$(jobCost) : "—"}
                          </td>
                        )}
                        <td style={{ padding: "9px 14px", color: "var(--text3)" }}>
                          {job.created_at ? new Date(job.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Section>
        </>
      )}
    </AppLayout>
  );
}
