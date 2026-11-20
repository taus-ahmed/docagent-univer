"use client";

// Overnight H1: the firm's audit log — who signed in, edited, exported,
// deleted or changed access, and when. Read-only; the server scopes it to
// the administrator's own firm and never stores document contents.
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { adminApi, type AuditPage } from "@/lib/api";

const PAGE_SIZE = 50;

export default function AuditLogPage() {
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [outcome, setOutcome] = useState("");

  const q = useQuery<AuditPage>({
    queryKey: ["audit", page, action, actor, outcome],
    queryFn: () => adminApi.audit({
      page, page_size: PAGE_SIZE,
      action: action || undefined, actor: actor || undefined,
      outcome: outcome || undefined,
    }),
  });
  const data = q.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <AppLayout>
      <div style={{ padding: 24, maxWidth: 1200 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 4 }}>Audit log</h1>
        <p style={{ fontSize: 12, color: "var(--text3)", marginBottom: 16 }}>
          Every sign-in, user and password change, template change, job, export and
          review action in your firm. It records who, when and what was acted on —
          never document contents.
        </p>
        <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
          <select className="input" aria-label="Action" value={action}
                  onChange={e => { setAction(e.target.value); setPage(1); }}>
            <option value="">All actions</option>
            {(data?.actions ?? []).map(a => <option key={a} value={a}>{a}</option>)}
          </select>
          <input className="input" aria-label="User" placeholder="User name" value={actor}
                 onChange={e => { setActor(e.target.value); setPage(1); }}/>
          <select className="input" aria-label="Outcome" value={outcome}
                  onChange={e => { setOutcome(e.target.value); setPage(1); }}>
            <option value="">Any outcome</option>
            <option value="ok">ok</option>
            <option value="failed">failed</option>
          </select>
        </div>
        {q.isError && <p role="alert" style={{ color: "var(--red)" }}>
          The audit log could not be loaded (administrators only).</p>}
        {q.isLoading && <p style={{ color: "var(--text3)" }}>Loading…</p>}
        {data && (
          <>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  {["When (UTC)", "User", "Action", "Target", "Outcome", "Request"].map(h => (
                    <th key={h} style={{ textAlign: "left", padding: "6px 8px",
                                         borderBottom: "1px solid var(--border)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.events.map(e => (
                  <tr key={e.id}>
                    <td style={{ padding: "4px 8px" }}>{e.at?.replace("T", " ").slice(0, 19)}</td>
                    <td style={{ padding: "4px 8px" }}>{e.actor ?? "—"}</td>
                    <td style={{ padding: "4px 8px" }}>{e.action}</td>
                    <td style={{ padding: "4px 8px" }}>
                      {e.target_type ? `${e.target_type} ${e.target_id ?? ""}` : "—"}</td>
                    <td style={{ padding: "4px 8px", color: e.outcome === "ok" ? undefined : "var(--red)" }}>
                      {e.outcome}</td>
                    <td style={{ padding: "4px 8px", fontFamily: "monospace" }}>{e.request_id ?? ""}</td>
                  </tr>
                ))}
                {!data.events.length && (
                  <tr><td colSpan={6} style={{ padding: 12, color: "var(--text3)" }}>No events.</td></tr>
                )}
              </tbody>
            </table>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 12 }}>
              <button className="btn btn-secondary btn-sm" disabled={page <= 1}
                      onClick={() => setPage(p => p - 1)}>‹ Previous</button>
              <span style={{ fontSize: 12 }}>Page {page} of {pages} · {data.total} events</span>
              <button className="btn btn-secondary btn-sm" disabled={page >= pages}
                      onClick={() => setPage(p => p + 1)}>Next ›</button>
            </div>
          </>
        )}
      </div>
    </AppLayout>
  );
}
