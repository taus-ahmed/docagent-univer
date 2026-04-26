"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { adminApi, schemasApi, type User, type SystemStats } from "@/lib/api";
import toast from "react-hot-toast";

function StatCard({ label, value, color = "var(--accent)" }: { label: string; value: number; color?: string }) {
  return (
    <div className="card" style={{ padding: "14px 18px", display: "flex", alignItems: "center", gap: 14 }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 11, color: "var(--text3)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>{label}</div>
        <div style={{ fontSize: 26, fontWeight: 700, color: "var(--text1)", fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>{value}</div>
      </div>
      <div style={{ width: 36, height: 36, borderRadius: 9, background: `${color}18`, display: "grid", placeItems: "center" }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "client", client_id: "", email: "" });

  const { data: stats } = useQuery<SystemStats>({ queryKey: ["admin-stats"], queryFn: adminApi.stats, refetchInterval: 30_000 });
  const { data: users = [], isLoading } = useQuery<User[]>({ queryKey: ["admin-users"], queryFn: adminApi.listUsers });
  const { data: schemas = [] } = useQuery({ queryKey: ["schemas"], queryFn: schemasApi.list });

  const createMutation = useMutation({
    mutationFn: () => adminApi.createUser({
      username: form.username, display_name: form.display_name,
      password: form.password, role: form.role,
      client_id: form.client_id || undefined,
      email: form.email || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users", "admin-stats"] });
      toast.success("User created");
      setShowCreate(false);
      setForm({ username: "", display_name: "", password: "", role: "client", client_id: "", email: "" });
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Create failed"),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: number) => adminApi.deactivateUser(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["admin-users"] }); toast.success("User deactivated"); },
  });

  const field = (key: string) => ({
    value: (form as any)[key],
    onChange: (e: any) => setForm(p => ({ ...p, [key]: e.target.value })),
  });

  return (
    <AppLayout>
      <style>{`
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 10px; margin-bottom: 28px; }
        .user-row {
          display: flex; align-items: center; gap: 12px;
          padding: 11px 14px; background: var(--surface);
          border: 1px solid var(--border); border-radius: 9px; margin-bottom: 5px;
        }
        .u-avatar {
          width: 32px; height: 32px; border-radius: 50%;
          background: var(--accent-dim); border: 1px solid var(--accent-border);
          color: var(--accent); display: grid; place-items: center;
          font-size: 12px; font-weight: 600; flex-shrink: 0;
        }
        .u-name { font-size: 13px; font-weight: 500; color: var(--text1); }
        .u-meta { font-size: 11px; color: var(--text3); margin-top: 1px; }
        .role-admin { background: rgba(245,158,11,0.1); color: var(--amber); padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
        .role-client { background: var(--accent-dim); color: var(--accent); padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
        .create-form { background: var(--surface); border: 1px solid var(--border); border-radius: 11px; padding: 18px; margin-top: 12px; }
        .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
        .form-field label { display: block; font-size: 11px; font-weight: 500; color: var(--text2); margin-bottom: 5px; }
      `}</style>

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 22 }}>
        <div>
          <h1 className="page-title">Admin</h1>
          <p className="page-sub">System overview and user management</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(p => !p)}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          New user
        </button>
      </div>

      {stats && (
        <div className="stats-grid">
          <StatCard label="Total jobs" value={stats.total_jobs} />
          <StatCard label="Documents" value={stats.total_documents} />
          <StatCard label="Users" value={stats.total_users} />
          <StatCard label="Reviewed" value={stats.documents_reviewed} color="var(--green)" />
          <StatCard label="Pending review" value={stats.documents_pending_review} color="var(--amber)" />
          <StatCard label="High confidence" value={stats.high_confidence_docs} color="var(--green)" />
          <StatCard label="Jobs (7 days)" value={stats.jobs_last_7_days} color="var(--blue)" />
        </div>
      )}

      {showCreate && (
        <div className="create-form">
          <p style={{ fontSize: 14, fontWeight: 600, color: "var(--text1)", marginBottom: 14 }}>Create user</p>
          <div className="form-grid">
            {[
              { label: "Username", key: "username", placeholder: "jsmith", type: "text" },
              { label: "Display name", key: "display_name", placeholder: "Jane Smith", type: "text" },
              { label: "Password", key: "password", placeholder: "Min 6 chars", type: "password" },
              { label: "Email", key: "email", placeholder: "jane@company.com (optional)", type: "email" },
            ].map(({ label, key, placeholder, type }) => (
              <div key={key} className="form-field">
                <label>{label}</label>
                <input className="input" type={type} placeholder={placeholder} {...field(key)} />
              </div>
            ))}
            <div className="form-field">
              <label>Role</label>
              <select className="input" {...field("role")} style={{ appearance: "none" }}>
                <option value="client">Client</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="form-field">
              <label>Client schema (optional)</label>
              <select className="input" {...field("client_id")} style={{ appearance: "none" }}>
                <option value="">(none)</option>
                {schemas.map(s => <option key={s.client_id} value={s.client_id}>{s.client_name}</option>)}
              </select>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 14 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowCreate(false)}>Cancel</button>
            <button className="btn btn-primary btn-sm" onClick={() => createMutation.mutate()} disabled={createMutation.isPending}>
              {createMutation.isPending ? "Creating…" : "Create user"}
            </button>
          </div>
        </div>
      )}

      <div style={{ marginTop: 24 }}>
        <p className="label" style={{ marginBottom: 10 }}>Users ({users.length})</p>
        {isLoading ? (
          <p style={{ fontSize: 13, color: "var(--text3)" }}>Loading…</p>
        ) : (
          users.map(u => (
            <div key={u.id} className="user-row">
              <div className="u-avatar">{u.display_name[0]?.toUpperCase()}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="u-name">{u.display_name}</div>
                <div className="u-meta">@{u.username}{u.client_id ? ` · ${u.client_id}` : ""}{u.email ? ` · ${u.email}` : ""}</div>
              </div>
              <span className={u.role === "admin" ? "role-admin" : "role-client"}>{u.role}</span>
              {!u.is_active && <span style={{ fontSize: 11, color: "var(--text4)" }}>inactive</span>}
              {u.role !== "admin" && u.is_active && (
                <button className="btn btn-ghost btn-sm" style={{ color: "var(--red)", fontSize: 12 }}
                  onClick={() => { if (confirm(`Deactivate ${u.username}?`)) deactivateMutation.mutate(u.id); }}>
                  Deactivate
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </AppLayout>
  );
}
