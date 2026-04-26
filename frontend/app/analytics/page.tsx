"use client";

import { useQuery } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { extractApi, adminApi, type JobStatus } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div style={{ height: 6, background: "var(--surface3)", borderRadius: 3, overflow: "hidden", marginTop: 4 }}>
      <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.6s ease" }} />
    </div>
  );
}

export default function AnalyticsPage() {
  const router = useRouter();
  const { user } = useAuthStore();

  useEffect(() => {
    if (user && user.role !== "admin") router.replace("/extract");
  }, [user, router]);

  const { data: jobs = [] } = useQuery<JobStatus[]>({
    queryKey: ["jobs"],
    queryFn: () => extractApi.listJobs({ limit: 200 }),
  });
  const { data: stats } = useQuery({ queryKey: ["admin-stats"], queryFn: adminApi.stats });

  const completed = jobs.filter(j => j.status === "completed");
  const failed = jobs.filter(j => j.status === "failed");
  const totalDocs = completed.reduce((s, j) => s + j.total_docs, 0);
  const totalSuccessful = completed.reduce((s, j) => s + j.successful, 0);
  const avgTime = completed.length
    ? (completed.reduce((s, j) => s + j.total_time_sec, 0) / completed.length).toFixed(1)
    : "—";

  // Jobs by day (last 14 days)
  const now = Date.now();
  const dayMs = 86_400_000;
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date(now - (13 - i) * dayMs);
    const label = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    const count = jobs.filter(j => {
      const jd = new Date(j.created_at);
      return jd.toDateString() === d.toDateString();
    }).length;
    return { label, count };
  });
  const maxDay = Math.max(...days.map(d => d.count), 1);

  const sourceBreakdown = [
    { label: "Upload", count: jobs.filter(j => j.input_source === "upload").length, color: "var(--accent)" },
    { label: "Drive",  count: jobs.filter(j => j.input_source === "drive").length,  color: "var(--blue)" },
    { label: "Folder", count: jobs.filter(j => j.input_source === "folder").length, color: "var(--green)" },
  ].filter(s => s.count > 0);

  return (
    <AppLayout>
      <style>{`
        .an-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin-bottom: 28px; }
        .an-card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
        .an-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.07em; color: var(--text3); margin-bottom: 6px; }
        .an-val { font-size: 28px; font-weight: 700; color: var(--text1); line-height: 1; font-variant-numeric: tabular-nums; }
        .an-sub { font-size: 11px; color: var(--text3); margin-top: 3px; }
        .chart-card { background: var(--surface); border: 1px solid var(--border); border-radius: 11px; padding: 18px; margin-bottom: 14px; }
        .chart-title { font-size: 13px; font-weight: 600; color: var(--text1); margin-bottom: 14px; }
        .day-bars { display: flex; align-items: flex-end; gap: 4px; height: 80px; }
        .day-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; }
        .day-bar { width: 100%; background: var(--accent); border-radius: 3px 3px 0 0; min-height: 3px; transition: height 0.4s ease; }
        .day-label { font-size: 9px; color: var(--text4); white-space: nowrap; }
        .day-val { font-size: 9px; color: var(--text3); font-weight: 500; }
        .src-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
        .src-label { font-size: 12px; color: var(--text2); width: 60px; }
        .src-bar-wrap { flex: 1; }
        .src-count { font-size: 12px; color: var(--text3); font-variant-numeric: tabular-nums; min-width: 24px; text-align: right; }
      `}</style>

      <div style={{ marginBottom: 22 }}>
        <h1 className="page-title">Analytics</h1>
        <p className="page-sub">Extraction performance overview</p>
      </div>

      {jobs.length === 0 ? (
        <div className="card" style={{ padding: "48px 32px", textAlign: "center" }}>
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5" style={{ margin: "0 auto 12px", display: "block" }}><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
          <p style={{ fontWeight: 500, color: "var(--text2)" }}>No data yet</p>
          <p style={{ fontSize: 12, color: "var(--text3)", marginTop: 4 }}>Analytics will appear after your first extractions</p>
        </div>
      ) : (
        <>
          <div className="an-grid">
            <div className="an-card">
              <div className="an-label">Total jobs</div>
              <div className="an-val">{jobs.length}</div>
              <div className="an-sub">{completed.length} completed</div>
            </div>
            <div className="an-card">
              <div className="an-label">Documents</div>
              <div className="an-val">{totalDocs}</div>
              <div className="an-sub">{totalSuccessful} successful</div>
            </div>
            <div className="an-card">
              <div className="an-label">Success rate</div>
              <div className="an-val" style={{ color: "var(--green)" }}>
                {totalDocs > 0 ? Math.round((totalSuccessful / totalDocs) * 100) : 0}%
              </div>
            </div>
            <div className="an-card">
              <div className="an-label">Avg time/job</div>
              <div className="an-val">{avgTime}<span style={{ fontSize: 14, fontWeight: 400, color: "var(--text3)" }}>s</span></div>
            </div>
            <div className="an-card">
              <div className="an-label">Failed</div>
              <div className="an-val" style={{ color: failed.length > 0 ? "var(--red)" : "var(--text1)" }}>{failed.length}</div>
            </div>
            {stats && (
              <div className="an-card">
                <div className="an-label">Pending review</div>
                <div className="an-val" style={{ color: stats.documents_pending_review > 0 ? "var(--amber)" : "var(--text1)" }}>
                  {stats.documents_pending_review}
                </div>
              </div>
            )}
          </div>

          {/* Daily chart */}
          <div className="chart-card">
            <div className="chart-title">Jobs per day (last 14 days)</div>
            <div className="day-bars">
              {days.map((d, i) => (
                <div key={i} className="day-col">
                  <div className="day-val">{d.count > 0 ? d.count : ""}</div>
                  <div className="day-bar" style={{ height: `${Math.max((d.count / maxDay) * 60, d.count > 0 ? 4 : 0)}px`, opacity: d.count > 0 ? 1 : 0.2 }} />
                  <div className="day-label">{d.label.split(" ")[1]}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Source breakdown */}
          {sourceBreakdown.length > 0 && (
            <div className="chart-card">
              <div className="chart-title">Source breakdown</div>
              {sourceBreakdown.map(s => (
                <div key={s.label} className="src-row">
                  <span className="src-label">{s.label}</span>
                  <div className="src-bar-wrap">
                    <Bar value={s.count} max={jobs.length} color={s.color} />
                  </div>
                  <span className="src-count">{s.count}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </AppLayout>
  );
}
