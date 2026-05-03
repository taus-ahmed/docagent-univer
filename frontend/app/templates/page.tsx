"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { templatesApi, type ColumnTemplate } from "@/lib/api";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";

const DOC_TYPE_COLORS: Record<string, string> = {
  invoice:        "#6366f1",
  receipt:        "#10b981",
  purchase_order: "#f59e0b",
  bank_statement: "#3b82f6",
  contract:       "#8b5cf6",
  other:          "#6b7280",
};

export default function TemplatesPage() {
  const router = useRouter();
  const qc = useQueryClient();

  const { data: templates = [], isLoading } = useQuery<ColumnTemplate[]>({
    queryKey: ["templates"],
    staleTime: 0,
    refetchOnMount: true,
    refetchOnWindowFocus: true,
    queryFn: () => templatesApi.list(),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => templatesApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["templates"] }); toast.success("Deleted"); },
    onError: () => toast.error("Delete failed"),
  });

  const grouped = templates.reduce<Record<string, ColumnTemplate[]>>((acc, t) => {
    if (!acc[t.document_type]) acc[t.document_type] = [];
    acc[t.document_type].push(t);
    return acc;
  }, {});

  return (
    <AppLayout>
      <style>{`
        .tpl-page-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 24px; }
        .tpl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; margin-bottom: 28px; }
        .tpl-card {
          background: var(--surface); border: 1px solid var(--border);
          border-radius: 10px; padding: 14px; cursor: pointer;
          transition: border-color 0.12s, box-shadow 0.12s; position: relative;
        }
        .tpl-card:hover { border-color: var(--border2); box-shadow: 0 2px 8px rgba(0,0,0,0.04); }
        .tpl-card-top { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; }
        .tpl-card-icon { width: 32px; height: 32px; border-radius: 7px; display: grid; place-items: center; flex-shrink: 0; }
        .tpl-card-name { font-size: 13.5px; font-weight: 600; color: var(--text1); margin-bottom: 2px; }
        .tpl-card-meta { font-size: 11px; color: var(--text3); }
        .tpl-card-cols { display: flex; flex-wrap: wrap; gap: 4px; }
        .tpl-col-pill { padding: 2px 6px; background: var(--bg); border: 1px solid var(--border); border-radius: 4px; font-size: 10px; color: var(--text3); }
        .tpl-card-actions { position: absolute; top: 10px; right: 10px; display: flex; gap: 4px; opacity: 0; transition: opacity 0.1s; }
        .tpl-card:hover .tpl-card-actions { opacity: 1; }
        .tpl-group-label { display: flex; align-items: center; gap: 7px; font-size: 11px; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text3); margin-bottom: 10px; }
        .tpl-empty { padding: 52px 32px; text-align: center; }
      `}</style>

      <div className="tpl-page-header">
        <div>
          <h1 className="page-title">Templates</h1>
          <p className="page-sub">Define column layouts for document extraction</p>
        </div>
        <button className="btn btn-primary" onClick={() => router.push("/templates/new")}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          New template
        </button>
      </div>

      {isLoading ? (
        <p style={{ color: "var(--text3)", fontSize: 13 }}>Loadingâ€¦</p>
      ) : templates.length === 0 ? (
        <div className="card tpl-empty">
          <div style={{ width: 44, height: 44, borderRadius: 11, background: "var(--surface2)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 14px" }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text3)" strokeWidth="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
          </div>
          <p style={{ fontWeight: 600, color: "var(--text1)", marginBottom: 6 }}>No templates yet</p>
          <p style={{ fontSize: 12, color: "var(--text3)", marginBottom: 16 }}>Templates define which columns appear in extraction results</p>
          <button className="btn btn-primary" onClick={() => router.push("/templates/new")}>Create your first template</button>
        </div>
      ) : (
        Object.entries(grouped).map(([docType, items]) => {
          const color = DOC_TYPE_COLORS[docType] ?? "#6b7280";
          return (
            <div key={docType} style={{ marginBottom: 28 }}>
              <div className="tpl-group-label">
                <span style={{ width: 7, height: 7, borderRadius: "50%", background: color, display: "inline-block" }} />
                {docType.replace(/_/g, " ")}
                <span style={{ color: "var(--text4)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>({items.length})</span>
              </div>
              <div className="tpl-grid">
                {items.map(t => (
                  <div
                    key={t.id}
                    className="tpl-card"
                    onClick={() => router.push(`/templates/edit?id=${t.id}`)}
                  >
                    <div className="tpl-card-actions">
                      <button
                        className="btn btn-ghost btn-sm btn-icon"
                        onClick={e => { e.stopPropagation(); if (confirm("Delete this template?")) deleteMutation.mutate(t.id); }}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
                      </button>
                    </div>
                    <div className="tpl-card-top">
                      <div className="tpl-card-icon" style={{ background: `${color}15` }}>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                      </div>
                      <div>
                        <div className="tpl-card-name">{t.name}</div>
                        <div className="tpl-card-meta">{t.columns.length} column{t.columns.length !== 1 ? "s" : ""}{t.is_shared ? " Â· shared" : ""}</div>
                      </div>
                    </div>
                    <div className="tpl-card-cols">
                      {t.columns.slice(0, 5).map(c => <span key={c.name} className="tpl-col-pill">{c.name}</span>)}
                      {t.columns.length > 5 && <span className="tpl-col-pill">+{t.columns.length - 5}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })
      )}
    </AppLayout>
  );
}
