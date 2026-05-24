"use client";

import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { adminApi, type User, type SystemStats } from "@/lib/api";
import toast from "react-hot-toast";

// ── Types ─────────────────────────────────────────────────────────────────────
type FormMode = "create" | "edit" | null;

interface UserForm {
  username: string;
  display_name: string;
  password: string;
  email: string;
  role: string;
  client_id: string;
}

const EMPTY_FORM: UserForm = {
  username: "", display_name: "", password: "",
  email: "", role: "client", client_id: "",
};

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, color = "var(--accent)", icon }: {
  label: string; value: number; color?: string; icon: React.ReactNode;
}) {
  return (
    <div style={{
      background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: 10, padding: "14px 18px",
      display: "flex", alignItems: "center", gap: 14,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 10, color: "var(--text3)", fontWeight: 700,
          textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
          {label}
        </div>
        <div style={{ fontSize: 24, fontWeight: 700, color: "var(--text1)",
          fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
          {value}
        </div>
      </div>
      <div style={{ width: 34, height: 34, borderRadius: 8,
        background: `${color}18`, display: "grid", placeItems: "center",
        color, flexShrink: 0 }}>
        {icon}
      </div>
    </div>
  );
}

// ── Role badge ────────────────────────────────────────────────────────────────
function RoleBadge({ role }: { role: string }) {
  const styles: Record<string, React.CSSProperties> = {
    admin: { background: "rgba(245,158,11,0.12)", color: "#f59e0b" },
    client: { background: "var(--accent-dim)", color: "var(--accent)" },
    company_admin: { background: "rgba(16,185,129,0.12)", color: "#10b981" },
  };
  return (
    <span style={{
      ...(styles[role] ?? styles.client),
      padding: "2px 8px", borderRadius: 999,
      fontSize: 10, fontWeight: 700, letterSpacing: "0.04em",
      textTransform: "uppercase",
    }}>
      {role === "company_admin" ? "Co. Admin" : role}
    </span>
  );
}

// ── User form modal ───────────────────────────────────────────────────────────
function UserFormModal({
  mode, initial, companies,
  onClose, onSave,
}: {
  mode: FormMode;
  initial?: User;
  companies: string[];
  onClose: () => void;
  onSave: (form: UserForm) => void;
}) {
  const [form, setForm] = useState<UserForm>(
    initial
      ? { username: initial.username, display_name: initial.display_name,
          password: "", email: initial.email ?? "",
          role: initial.role, client_id: initial.client_id ?? "" }
      : EMPTY_FORM
  );

  const set = (k: keyof UserForm) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
      setForm(p => ({ ...p, [k]: e.target.value }));

  const isCreate = mode === "create";

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)",
      display: "flex", alignItems: "center", justifyContent: "center",
      zIndex: 1000, padding: 20,
    }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        background: "var(--surface)", border: "1px solid var(--border)",
        borderRadius: 14, padding: 24, width: "100%", maxWidth: 480,
        boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
      }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, color: "var(--text1)", marginBottom: 20 }}>
          {isCreate ? "Create user" : `Edit — ${initial?.display_name}`}
        </h2>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {/* Username — only on create */}
          {isCreate && (
            <div style={{ gridColumn: "1 / -1" }}>
              <label className="form-label">Username</label>
              <input className="input" placeholder="jsmith" value={form.username} onChange={set("username")} />
            </div>
          )}

          <div>
            <label className="form-label">Display name</label>
            <input className="input" placeholder="Jane Smith" value={form.display_name} onChange={set("display_name")} />
          </div>

          <div>
            <label className="form-label">Email</label>
            <input className="input" type="email" placeholder="jane@co.com" value={form.email} onChange={set("email")} />
          </div>

          <div>
            <label className="form-label">{isCreate ? "Password" : "New password (leave blank to keep)"}</label>
            <input className="input" type="password" placeholder={isCreate ? "Min 6 chars" : "Leave blank to keep"}
              value={form.password} onChange={set("password")} />
          </div>

          <div>
            <label className="form-label">Role</label>
            <select className="input" value={form.role} onChange={set("role")} style={{ appearance: "none" }}>
              <option value="client">Client</option>
              <option value="company_admin">Company Admin</option>
              <option value="admin">Super Admin</option>
            </select>
          </div>

          <div style={{ gridColumn: "1 / -1" }}>
            <label className="form-label">Company (client_id)</label>
            <div style={{ display: "flex", gap: 8 }}>
              <input className="input" placeholder="e.g. accounting_firm_a"
                value={form.client_id} onChange={set("client_id")}
                list="company-list" style={{ flex: 1 }} />
              <datalist id="company-list">
                {companies.map(c => <option key={c} value={c} />)}
              </datalist>
            </div>
            <p style={{ fontSize: 10, color: "var(--text4)", marginTop: 4 }}>
              Users with the same client_id are isolated from other companies
            </p>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 20 }}>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary btn-sm" onClick={() => onSave(form)}>
            {isCreate ? "Create user" : "Save changes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function AdminPage() {
  const qc = useQueryClient();
  const [formMode, setFormMode] = useState<FormMode>(null);
  const [editTarget, setEditTarget] = useState<User | null>(null);
  const [companyFilter, setCompanyFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  // Data
  const { data: stats } = useQuery<SystemStats>({
    queryKey: ["admin-stats"],
    queryFn: adminApi.stats,
    refetchInterval: 30_000,
  });

  const { data: users = [], isLoading } = useQuery<User[]>({
    queryKey: ["admin-users"],
    queryFn: adminApi.listUsers,
  });

  // Derive company list from existing users
  const companies = useMemo(() => {
    const set = new Set<string>();
    users.forEach(u => { if (u.client_id) set.add(u.client_id); });
    return Array.from(set).sort();
  }, [users]);

  // Filter users
  const filtered = useMemo(() => {
    return users.filter(u => {
      if (!showInactive && !u.is_active) return false;
      if (companyFilter !== "all" && u.client_id !== companyFilter) return false;
      if (search) {
        const q = search.toLowerCase();
        if (!u.username.toLowerCase().includes(q) &&
            !u.display_name.toLowerCase().includes(q) &&
            !(u.email ?? "").toLowerCase().includes(q) &&
            !(u.client_id ?? "").toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [users, companyFilter, search, showInactive]);

  // Group by company
  const grouped = useMemo(() => {
    const map = new Map<string, User[]>();
    filtered.forEach(u => {
      const key = u.client_id || "(no company)";
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(u);
    });
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  // Mutations
  const createMutation = useMutation({
    mutationFn: (f: UserForm) => adminApi.createUser({
      username: f.username, display_name: f.display_name,
      password: f.password, role: f.role,
      client_id: f.client_id || undefined,
      email: f.email || undefined,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["admin-stats"] });
      toast.success("User created");
      setFormMode(null);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Create failed"),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, f }: { id: number; f: UserForm }) => adminApi.updateUser(id, {
      display_name: f.display_name,
      email: f.email || undefined,
      role: f.role,
      client_id: f.client_id || undefined,
      ...(f.password ? { password: f.password } : {}),
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User updated");
      setFormMode(null);
      setEditTarget(null);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Update failed"),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: number) => adminApi.deactivateUser(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User deactivated");
    },
  });

  const reactivateMutation = useMutation({
    mutationFn: (id: number) => adminApi.updateUser(id, { is_active: true }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User reactivated");
    },
  });

  function openEdit(u: User) {
    setEditTarget(u);
    setFormMode("edit");
  }

  function handleSave(form: UserForm) {
    if (formMode === "create") {
      createMutation.mutate(form);
    } else if (formMode === "edit" && editTarget) {
      updateMutation.mutate({ id: editTarget.id, f: form });
    }
  }

  return (
    <AppLayout>
      <style>{`
        .form-label {
          display: block; font-size: 11px; font-weight: 600;
          color: var(--text3); margin-bottom: 5px;
          text-transform: uppercase; letter-spacing: 0.04em;
        }
        .user-row {
          display: flex; align-items: center; gap: 10px;
          padding: 10px 14px; background: var(--surface);
          border: 1px solid var(--border); border-radius: 9px;
          margin-bottom: 4px; transition: border-color 0.12s;
        }
        .user-row:hover { border-color: var(--border2); }
        .user-row.inactive { opacity: 0.5; }
        .u-avatar {
          width: 30px; height: 30px; border-radius: 50%;
          background: var(--accent-dim); color: var(--accent);
          display: grid; place-items: center;
          font-size: 11px; font-weight: 700; flex-shrink: 0;
        }
        .company-section { margin-bottom: 20px; }
        .company-header {
          display: flex; align-items: center; gap: 8; margin-bottom: 8px;
          padding: 6px 10px; background: var(--surface2);
          border-radius: 7px; border: 1px solid var(--border);
        }
      `}</style>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "flex-start",
        justifyContent: "space-between", marginBottom: 22, flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="page-title">Admin</h1>
          <p className="page-sub">User management and system overview</p>
        </div>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setFormMode("create"); }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          New user
        </button>
      </div>

      {/* Stats */}
      {stats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px,1fr))",
          gap: 10, marginBottom: 28 }}>
          <StatCard label="Total jobs" value={stats.total_jobs}
            icon={<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>} />
          <StatCard label="Documents" value={stats.total_documents} color="var(--green)"
            icon={<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>} />
          <StatCard label="Active users" value={stats.total_users}
            icon={<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>} />
          <StatCard label="Pending review" value={stats.documents_pending_review} color="var(--amber)"
            icon={<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>} />
          <StatCard label="Jobs (7 days)" value={stats.jobs_last_7_days} color="var(--blue)"
            icon={<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>} />
          <StatCard label="Companies" value={companies.length} color="#8b5cf6"
            icon={<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>} />
        </div>
      )}

      {/* Filters */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
        <input className="input" placeholder="Search users…" value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ width: 220, fontSize: 13 }} />

        <select className="input" value={companyFilter}
          onChange={e => setCompanyFilter(e.target.value)}
          style={{ appearance: "none", width: 200, fontSize: 13 }}>
          <option value="all">All companies</option>
          <option value="">(no company)</option>
          {companies.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        <label style={{ display: "flex", alignItems: "center", gap: 6,
          fontSize: 12, color: "var(--text2)", cursor: "pointer" }}>
          <input type="checkbox" checked={showInactive}
            onChange={e => setShowInactive(e.target.checked)} />
          Show inactive
        </label>

        <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--text3)",
          alignSelf: "center" }}>
          {filtered.length} user{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* User list grouped by company */}
      {isLoading ? (
        <p style={{ fontSize: 13, color: "var(--text3)" }}>Loading…</p>
      ) : filtered.length === 0 ? (
        <div style={{ padding: "40px 0", textAlign: "center", color: "var(--text3)", fontSize: 13 }}>
          No users match your filters
        </div>
      ) : (
        grouped.map(([company, companyUsers]) => (
          <div key={company} className="company-section">
            {/* Company header */}
            <div className="company-header">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none"
                stroke="var(--text3)" strokeWidth="2">
                <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                <polyline points="9 22 9 12 15 12 15 22"/>
              </svg>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text2)" }}>
                {company}
              </span>
              <span style={{ fontSize: 11, color: "var(--text4)", marginLeft: 4 }}>
                {companyUsers.length} user{companyUsers.length !== 1 ? "s" : ""}
              </span>
            </div>

            {/* Users in this company */}
            {companyUsers.map(u => (
              <div key={u.id} className={`user-row${u.is_active ? "" : " inactive"}`}>
                <div className="u-avatar">
                  {u.display_name[0]?.toUpperCase() ?? "?"}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text1)" }}>
                    {u.display_name}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text3)", marginTop: 1 }}>
                    @{u.username}
                    {u.email && ` · ${u.email}`}
                    {!u.is_active && <span style={{ color: "var(--red)", marginLeft: 4 }}>inactive</span>}
                  </div>
                </div>

                <RoleBadge role={u.role} />

                {/* Actions */}
                <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                  <button className="btn btn-ghost btn-sm" onClick={() => openEdit(u)}
                    title="Edit user">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                      stroke="currentColor" strokeWidth="2">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                    Edit
                  </button>

                  {u.is_active ? (
                    <button className="btn btn-ghost btn-sm"
                      style={{ color: "var(--red)", fontSize: 12 }}
                      onClick={() => {
                        if (confirm(`Deactivate ${u.username}? They won't be able to log in.`))
                          deactivateMutation.mutate(u.id);
                      }}>
                      Deactivate
                    </button>
                  ) : (
                    <button className="btn btn-ghost btn-sm"
                      style={{ color: "var(--green)", fontSize: 12 }}
                      onClick={() => reactivateMutation.mutate(u.id)}>
                      Reactivate
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ))
      )}

      {/* Modal */}
      {formMode && (
        <UserFormModal
          mode={formMode}
          initial={editTarget ?? undefined}
          companies={companies}
          onClose={() => { setFormMode(null); setEditTarget(null); }}
          onSave={handleSave}
        />
      )}
    </AppLayout>
  );
}
