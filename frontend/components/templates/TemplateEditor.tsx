"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { templatesApi, type TemplateColumn, type ColumnTemplate } from "@/lib/api";
import toast from "react-hot-toast";

const DOC_TYPES = [
  "invoice", "receipt", "purchase_order",
  "bank_statement", "contract", "other",
];

interface Props { templateId?: number }

export default function TemplateEditor({ templateId }: Props) {
  const router = useRouter();
  const qc = useQueryClient();

  const [name, setName] = useState("");
  const [docType, setDocType] = useState("invoice");
  const [columns, setColumns] = useState<TemplateColumn[]>([]);
  const [colTypes, setColTypes] = useState<Record<number, "header" | "lineitem">>({});
  const [selectedCol, setSelectedCol] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [SheetEditor, setSheetEditor] = useState<React.ComponentType<any> | null>(null);

  // Mount guard — prevents hydration mismatch
  useEffect(() => { setMounted(true); }, []);

  // Lazy-load the spreadsheet (client only)
  useEffect(() => {
    if (!mounted) return;
    import("@/components/templates/FortuneSheetEditor")
      .then(m => setSheetEditor(() => m.default))
      .catch(err => console.error("Sheet editor load failed:", err));
  }, [mounted]);

  // Load existing template if editing
  const { data: existing } = useQuery<ColumnTemplate>({
    queryKey: ["template", templateId],
    queryFn: () => templatesApi.get(templateId!),
    enabled: !!templateId,
  });

  useEffect(() => {
    if (!existing) return;
    setName(existing.name);
    setDocType(existing.document_type);
    const sorted = [...existing.columns].sort((a, b) => a.order - b.order);
    setColumns(sorted);
    const types: Record<number, "header" | "lineitem"> = {};
    sorted.forEach((col, i) => {
      types[i] = ((col as any).extraction_type ?? "header") === "lineitem"
        ? "lineitem" : "header";
    });
    setColTypes(types);
  }, [existing]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error("Template name is required");
      const validCols = columns.filter(c => c.name.trim());
      if (!validCols.length) throw new Error("Add at least one column name in row 1");

      const enriched = validCols.map((col, i) => ({
        name: col.name.trim(),
        type: col.type ?? "Text",
        order: i,
        extraction_type: colTypes[i] ?? "header",
      }));

      if (templateId) {
        return templatesApi.update(templateId, {
          name: name.trim(),
          document_type: docType,
          columns: enriched as any,
        });
      }
      return templatesApi.create({
        name: name.trim(),
        document_type: docType,
        columns: enriched as any,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      toast.success(templateId ? "Template updated" : "Template saved");
      setDirty(false);
      router.push("/templates");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const handleColumnsChange = useCallback((cols: TemplateColumn[]) => {
    setColumns(cols);
    setDirty(true);
  }, []);

  const handleColumnSelect = useCallback((idx: number) => {
    setSelectedCol(idx);
  }, []);

  function setColType(type: "header" | "lineitem") {
    if (selectedCol === null) return;
    setColTypes(prev => ({ ...prev, [selectedCol]: type }));
    setDirty(true);
  }

  const headerCols = columns.filter((_, i) => (colTypes[i] ?? "header") === "header" && columns[i]?.name?.trim());
  const lineCols   = columns.filter((_, i) => colTypes[i] === "lineitem" && columns[i]?.name?.trim());
  const selColName = selectedCol !== null ? (columns[selectedCol]?.name || `Column ${String.fromCharCode(65 + selectedCol)}`) : null;
  const selColType = selectedCol !== null ? (colTypes[selectedCol] ?? "header") : null;

  if (!mounted) return null;

  return (
    <AppLayout>
      {/* ── Top bar ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{ fontSize: 12, color: "var(--text3)", cursor: "pointer" }}
            onClick={() => router.push("/templates")}
          >
            Templates
          </span>
          <span style={{ color: "var(--border2)" }}>›</span>
          <input
            style={{
              fontSize: 16, fontWeight: 600, color: "var(--text1)",
              background: "transparent", border: "none",
              borderBottom: "1.5px solid transparent", outline: "none",
              padding: "2px 4px", letterSpacing: "-0.02em",
              transition: "border-color 0.15s", minWidth: 180,
            }}
            onFocus={e => e.currentTarget.style.borderBottomColor = "var(--accent)"}
            onBlur={e => e.currentTarget.style.borderBottomColor = "transparent"}
            value={name}
            onChange={e => { setName(e.target.value); setDirty(true); }}
            placeholder="Template name…"
            autoFocus={!templateId}
          />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text2)" }}>
            Type:
            <select
              className="input"
              style={{ width: "auto", padding: "4px 10px" }}
              value={docType}
              onChange={e => { setDocType(e.target.value); setDirty(true); }}
            >
              {DOC_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
          </div>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              if (dirty && !confirm("Discard changes?")) return;
              router.push("/templates");
            }}
          >
            Discard
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? "Saving…" : (
              <>
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                  <polyline points="17 21 17 13 7 13 7 21"/>
                  <polyline points="7 3 7 8 15 8"/>
                </svg>
                Save template
              </>
            )}
          </button>
        </div>
      </div>

      {/* ── Layout ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 216px", gap: 14, alignItems: "start" }}>

        {/* Sheet area */}
        <div>
          {/* Column type toolbar */}
          <div style={{
            display: "flex", alignItems: "center", gap: 8, padding: "8px 12px",
            background: "var(--surface)", border: "1px solid var(--border)",
            borderBottom: "none",
            borderRadius: "var(--radius-lg) var(--radius-lg) 0 0",
            flexWrap: "wrap",
          }}>
            <span style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.07em", color: "var(--text3)", marginRight: 4 }}>
              Column type:
            </span>

            <button
              onClick={() => setColType("header")}
              disabled={selectedCol === null}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                padding: "5px 11px", borderRadius: 6,
                fontSize: 12, fontWeight: 500, cursor: "pointer",
                border: `1.5px solid ${selectedCol !== null && selColType === "header" ? "#3b82f6" : "#bfdbfe"}`,
                background: selectedCol !== null && selColType === "header" ? "#dbeafe" : "#eff6ff",
                color: "#1d4ed8", opacity: selectedCol === null ? 0.5 : 1,
              }}
            >
              🔵 Header field
            </button>

            <button
              onClick={() => setColType("lineitem")}
              disabled={selectedCol === null}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                padding: "5px 11px", borderRadius: 6,
                fontSize: 12, fontWeight: 500, cursor: "pointer",
                border: `1.5px solid ${selectedCol !== null && selColType === "lineitem" ? "#22c55e" : "#bbf7d0"}`,
                background: selectedCol !== null && selColType === "lineitem" ? "#dcfce7" : "#f0fdf4",
                color: "#15803d", opacity: selectedCol === null ? 0.5 : 1,
              }}
            >
              🟢 Line item
            </button>

            {selColName && (
              <span style={{ fontSize: 11, color: "var(--text3)", marginLeft: 4 }}>
                Selected: <b style={{ color: "var(--text2)" }}>{selColName}</b>
                {selColType && <> · <span style={{ color: selColType === "header" ? "#1d4ed8" : "#15803d" }}>{selColType}</span></>}
              </span>
            )}

            <div style={{ marginLeft: "auto", display: "flex", gap: 14, fontSize: 10, color: "var(--text3)" }}>
              <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#3b82f6", marginRight: 3 }} />Header = extracted once</span>
              <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#22c55e", marginRight: 3 }} />Line item = per row</span>
            </div>
          </div>

          {/* Fortune Sheet */}
          {SheetEditor ? (
            <SheetEditor
              initialColumns={columns}
              colTypes={colTypes}
              onColumnsChange={handleColumnsChange}
              onColumnSelect={handleColumnSelect}
              height={480}
            />
          ) : (
            <div style={{
              height: 480, display: "flex", alignItems: "center", justifyContent: "center",
              background: "var(--surface2)", border: "1px solid var(--border)",
              borderRadius: "0 0 var(--radius-lg) var(--radius-lg)",
            }}>
              <div style={{ textAlign: "center" }}>
                <svg
                  width="24" height="24" viewBox="0 0 24 24" fill="none"
                  stroke="var(--accent)" strokeWidth="2"
                  style={{ margin: "0 auto 10px", display: "block",
                    animation: "spin 0.8s linear infinite" }}
                >
                  <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
                </svg>
                <p style={{ fontSize: 13, color: "var(--text3)" }}>Loading spreadsheet…</p>
              </div>
            </div>
          )}

          <p style={{ fontSize: 11, color: "var(--text3)", marginTop: 8 }}>
            💡 Type column names in <b>row 1</b>. Click a cell in row 1, then use the toolbar above to tag it as Header or Line Item. Rows 2+ are editable preview data.
          </p>
        </div>

        {/* Right panel */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

          {/* How it works */}
          <div className="card" style={{ padding: 14 }}>
            <div className="label" style={{ marginBottom: 8 }}>How column types work</div>
            <div style={{ fontSize: 11, color: "var(--text2)", lineHeight: 1.7 }}>
              <div style={{ marginBottom: 8 }}>
                <b style={{ color: "#1d4ed8" }}>🔵 Header field</b><br />
                Extracted <b>once per document</b>.<br />
                Invoice #, Vendor, Date, Total
              </div>
              <div>
                <b style={{ color: "#15803d" }}>🟢 Line item</b><br />
                Extracted for <b>every row</b>.<br />
                SKU, Item, Price, Qty, Subtotal
              </div>
            </div>
          </div>

          {/* Column list */}
          <div className="card" style={{ padding: 14 }}>
            <div className="label" style={{ marginBottom: 8 }}>
              Columns ({columns.filter(c => c.name.trim()).length})
            </div>

            {columns.filter(c => c.name.trim()).length === 0 ? (
              <p style={{ fontSize: 11, color: "var(--text3)" }}>Type names in row 1</p>
            ) : (
              <>
                {headerCols.length > 0 && (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "#3b82f6", marginBottom: 4 }}>
                      Header ({headerCols.length})
                    </div>
                    {headerCols.map(c => (
                      <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 5, padding: "3px 7px", borderRadius: 5, background: "#eff6ff", color: "#1d4ed8", fontSize: 11, marginBottom: 3 }}>
                        <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#3b82f6", flexShrink: 0 }} />
                        {c.name}
                      </div>
                    ))}
                  </div>
                )}
                {lineCols.length > 0 && (
                  <div>
                    <div style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "#22c55e", marginBottom: 4 }}>
                      Line Items ({lineCols.length})
                    </div>
                    {lineCols.map(c => (
                      <div key={c.name} style={{ display: "flex", alignItems: "center", gap: 5, padding: "3px 7px", borderRadius: 5, background: "#f0fdf4", color: "#15803d", fontSize: 11, marginBottom: 3 }}>
                        <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", flexShrink: 0 }} />
                        {c.name}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>

          {/* AI preview */}
          <div className="card" style={{ padding: 14 }}>
            <div className="label" style={{ marginBottom: 8 }}>AI extraction</div>
            <div style={{ background: "var(--surface2)", borderRadius: 7, padding: 10, fontSize: 11, color: "var(--text2)", lineHeight: 1.7, border: "1px solid var(--border)" }}>
              {headerCols.length + lineCols.length === 0 ? (
                "Add columns to see extraction preview."
              ) : (
                <>
                  AI extracts <b>{headerCols.length}</b> header field{headerCols.length !== 1 ? "s" : ""} once per doc
                  {lineCols.length > 0 && (
                    <> + <b>{lineCols.length}</b> line item field{lineCols.length !== 1 ? "s" : ""} per row.<br /><br />
                    Multi-item invoices → <b>1 row per line item</b>, header fields repeated.</>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
