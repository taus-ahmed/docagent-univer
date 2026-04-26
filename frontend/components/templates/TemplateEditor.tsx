"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { templatesApi, type TemplateColumn, type ColumnTemplate } from "@/lib/api";
import toast from "react-hot-toast";

const DOC_TYPES = ["invoice", "receipt", "purchase_order", "bank_statement", "contract", "other"];

interface Props {
  templateId?: number;
}

export default function TemplateEditor({ templateId }: Props) {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [docType, setDocType] = useState("invoice");
  const [columns, setColumns] = useState<TemplateColumn[]>([]);
  const [colTypes, setColTypes] = useState<Record<number, "header" | "lineitem">>({});
  const [selectedCol, setSelectedCol] = useState<number | null>(null);
  const [dirty, setDirty] = useState(false);
  const [UniverSheet, setUniverSheet] = useState<React.ComponentType<any> | null>(null);

  // Load Univer lazily (client only, no SSR)
  useEffect(() => {
    import("@/components/templates/UniverSheet").then(m => {
      setUniverSheet(() => m.default);
    }).catch(() => {
      // Univer not available — will show fallback
      setUniverSheet(null);
    });
  }, []);

  // Load existing template if editing
  const { data: existing } = useQuery<ColumnTemplate>({
    queryKey: ["template", templateId],
    queryFn: () => templatesApi.get(templateId!),
    enabled: !!templateId,
  });

  useEffect(() => {
    if (existing) {
      setName(existing.name);
      setDocType(existing.document_type);
      const sorted = [...existing.columns].sort((a, b) => a.order - b.order);
      setColumns(sorted);
      const types: Record<number, "header" | "lineitem"> = {};
      sorted.forEach((col, i) => {
        // Infer type from stored column type field
        types[i] = (col as any).extraction_type === "lineitem" ? "lineitem" : "header";
      });
      setColTypes(types);
    }
  }, [existing]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error("Template name is required");
      const validCols = columns.filter(c => c.name.trim());
      if (!validCols.length) throw new Error("Add at least one column in row 1");

      // Attach extraction_type to each column
      const enriched = validCols.map((col, i) => ({
        ...col,
        name: col.name.trim(),
        order: i,
        // Store lineitem flag in the type field prefix for backend
        type: col.type,
        // We'll store the extraction_type in description field as a tag
      }));

      // Build columns_json with extraction_type embedded
      const colsWithType = enriched.map((col, i) => ({
        name: col.name,
        type: col.type,
        order: i,
        extraction_type: colTypes[i] ?? "header",
      }));

      if (templateId) {
        return templatesApi.update(templateId, {
          name: name.trim(),
          document_type: docType,
          columns: colsWithType as any,
        });
      } else {
        return templatesApi.create({
          name: name.trim(),
          document_type: docType,
          columns: colsWithType as any,
        });
      }
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

  const setColType = (type: "header" | "lineitem") => {
    if (selectedCol === null) return;
    setColTypes(prev => ({ ...prev, [selectedCol]: type }));
    setDirty(true);
  };

  const headerCount = Object.values(colTypes).filter(t => t === "header").length;
  const lineItemCount = Object.values(colTypes).filter(t => t === "lineitem").length;

  return (
    <AppLayout>
      <style>{`
        .te-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; gap:12px; }
        .te-breadcrumb { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text3); }
        .te-bc-link { cursor:pointer; color:var(--text3); }
        .te-bc-link:hover { color:var(--text2); }
        .te-name-input { font-size:17px; font-weight:600; color:var(--text1); background:transparent; border:none; border-bottom:1.5px solid transparent; outline:none; padding:2px 4px; letter-spacing:-0.02em; transition:border-color 0.15s; min-width:200px; }
        .te-name-input:focus { border-bottom-color:var(--accent); }
        .te-name-input::placeholder { color:var(--text4); font-weight:400; }
        .te-body { display:grid; grid-template-columns:1fr 220px; gap:14px; align-items:start; }
        .te-sheet-wrap { display:flex; flex-direction:column; gap:0; }
        .te-toolbar { display:flex; align-items:center; gap:6px; padding:8px 12px; background:var(--surface); border:1px solid var(--border); border-bottom:none; border-radius:var(--radius-lg) var(--radius-lg) 0 0; flex-wrap:wrap; }
        .te-toolbar-label { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--text3); margin-right:4px; }
        .type-btn { display:flex; align-items:center; gap:5px; padding:5px 11px; border-radius:6px; font-size:12px; font-weight:500; cursor:pointer; border:1.5px solid transparent; transition:all 0.12s; }
        .type-btn-header { background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe; }
        .type-btn-header:hover { background:#dbeafe; }
        .type-btn-lineitem { background:#f0fdf4; color:#15803d; border-color:#bbf7d0; }
        .type-btn-lineitem:hover { background:#dcfce7; }
        .type-btn.active-h { background:#dbeafe; border-color:#3b82f6; box-shadow:0 0 0 2px rgba(59,130,246,0.15); }
        .type-btn.active-l { background:#dcfce7; border-color:#22c55e; box-shadow:0 0 0 2px rgba(34,197,94,0.15); }
        .te-legend { display:flex; align-items:center; gap:12px; margin-left:auto; font-size:11px; color:var(--text3); }
        .legend-dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:3px; }
        .side-panel { display:flex; flex-direction:column; gap:12px; }
        .sp-card { background:var(--surface); border:1px solid var(--border); border-radius:var(--radius-lg); padding:14px; }
        .sp-title { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--text3); margin-bottom:8px; }
        .col-chip { display:flex; align-items:center; gap:5px; padding:4px 8px; border-radius:5px; font-size:11px; margin-bottom:3px; }
        .col-chip-h { background:#eff6ff; color:#1d4ed8; }
        .col-chip-l { background:#f0fdf4; color:#15803d; }
        .chip-dot { width:6px; height:6px; border-radius:50%; flex-shrink:0; }
        .preview-box { background:var(--surface2); border-radius:6px; padding:10px; font-size:11px; color:var(--text2); line-height:1.7; border:1px solid var(--border); }
        .fallback-editor { border:1px solid var(--border); border-radius:0 0 var(--radius-lg) var(--radius-lg); }
      `}</style>

      {/* Header */}
      <div className="te-header">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div className="te-breadcrumb">
            <span className="te-bc-link" onClick={() => router.push("/templates")}>Templates</span>
            <span style={{ color: "var(--border2)" }}>›</span>
          </div>
          <input
            className="te-name-input"
            value={name}
            onChange={e => { setName(e.target.value); setDirty(true); }}
            placeholder="Template name…"
            autoFocus={!templateId}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text2)" }}>
            Doc type:
            <select
              className="input"
              style={{ width: "auto", padding: "4px 10px" }}
              value={docType}
              onChange={e => { setDocType(e.target.value); setDirty(true); }}
            >
              {DOC_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => { if (dirty && !confirm("Discard changes?")) return; router.push("/templates"); }}>
            Discard
          </button>
          <button className="btn btn-primary btn-sm" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
            {saveMutation.isPending ? "Saving…" : (
              <>
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
                Save template
              </>
            )}
          </button>
        </div>
      </div>

      <div className="te-body">
        {/* Sheet area */}
        <div className="te-sheet-wrap">
          {/* Custom toolbar above Univer */}
          <div className="te-toolbar">
            <span className="te-toolbar-label">Column type:</span>
            <button
              className={`type-btn type-btn-header ${selectedCol !== null && (colTypes[selectedCol] ?? "header") === "header" ? "active-h" : ""}`}
              onClick={() => setColType("header")}
              disabled={selectedCol === null}
              title="Header field — extracted once per document (e.g. Invoice Number, Vendor Name)"
            >
              <span style={{ fontSize: 10 }}>🔵</span> Header field
            </button>
            <button
              className={`type-btn type-btn-lineitem ${selectedCol !== null && colTypes[selectedCol] === "lineitem" ? "active-l" : ""}`}
              onClick={() => setColType("lineitem")}
              disabled={selectedCol === null}
              title="Line item — extracted for every row (e.g. SKU, Price, Qty)"
            >
              <span style={{ fontSize: 10 }}>🟢</span> Line item
            </button>

            {selectedCol !== null && (
              <span style={{ fontSize: 11, color: "var(--text3)", marginLeft: 4 }}>
                Column {String.fromCharCode(65 + selectedCol)}: {columns[selectedCol]?.name || "—"}
              </span>
            )}

            <div className="te-legend">
              <span><span className="legend-dot" style={{ background: "#3b82f6" }} />Header = once per doc</span>
              <span><span className="legend-dot" style={{ background: "#22c55e" }} />Line item = per row</span>
            </div>
          </div>

          {/* Univer spreadsheet */}
          {UniverSheet ? (
            <div style={{ borderRadius: "0 0 var(--radius-lg) var(--radius-lg)", overflow: "hidden", border: "1px solid var(--border)" }}>
              <UniverSheet
                initialColumns={columns}
                colTypes={colTypes}
                onColumnsChange={handleColumnsChange}
                onColumnSelect={(idx: number) => setSelectedCol(idx)}
                height={500}
              />
            </div>
          ) : (
            <div className="fallback-editor">
              <FallbackEditor
                columns={columns}
                colTypes={colTypes}
                selectedCol={selectedCol}
                onColumnsChange={cols => { setColumns(cols); setDirty(true); }}
                onColumnSelect={setSelectedCol}
              />
            </div>
          )}

          <p style={{ fontSize: 11, color: "var(--text3)", marginTop: 8 }}>
            💡 Row 1 = column headers. Rows 2+ = editable preview rows. Use the toolbar above to tag each column as Header or Line Item.
          </p>
        </div>

        {/* Right panel */}
        <div className="side-panel">
          {/* Column type info */}
          <div className="sp-card">
            <div className="sp-title">How column types work</div>
            <div style={{ fontSize: 11, color: "var(--text2)", lineHeight: 1.7 }}>
              <div style={{ marginBottom: 8 }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontWeight: 600, color: "#1d4ed8" }}>
                  🔵 Header field
                </span><br />
                Extracted <b>once per document</b>.<br />
                e.g. Invoice #, Vendor, Date, Total
              </div>
              <div>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 4, fontWeight: 600, color: "#15803d" }}>
                  🟢 Line item
                </span><br />
                Extracted for <b>every row</b> in the doc.<br />
                e.g. SKU, Item, Price, Qty, Subtotal
              </div>
            </div>
          </div>

          {/* Column list */}
          <div className="sp-card">
            <div className="sp-title">Template columns ({columns.filter(c => c.name).length})</div>
            {columns.filter(c => c.name.trim()).length === 0 ? (
              <p style={{ fontSize: 11, color: "var(--text3)" }}>Type column names in row 1</p>
            ) : (
              <>
                {Object.entries(
                  columns.filter(c => c.name.trim()).reduce<Record<string, string[]>>((acc, col, i) => {
                    const t = colTypes[i] ?? "header";
                    if (!acc[t]) acc[t] = [];
                    acc[t].push(col.name);
                    return acc;
                  }, {})
                ).map(([type, names]) => (
                  <div key={type} style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: type === "header" ? "#3b82f6" : "#22c55e", marginBottom: 4 }}>
                      {type === "header" ? "Header" : "Line Items"}
                    </div>
                    {names.map(n => (
                      <div key={n} className={`col-chip ${type === "header" ? "col-chip-h" : "col-chip-l"}`}>
                        <div className="chip-dot" style={{ background: type === "header" ? "#3b82f6" : "#22c55e" }} />
                        {n}
                      </div>
                    ))}
                  </div>
                ))}
              </>
            )}
          </div>

          {/* AI preview */}
          <div className="sp-card">
            <div className="sp-title">AI extraction</div>
            <div className="preview-box">
              {headerCount > 0 || lineItemCount > 0 ? (
                <>
                  AI will extract <b>{headerCount}</b> header field{headerCount !== 1 ? "s" : ""} once per document
                  {lineItemCount > 0 && (
                    <> + <b>{lineItemCount}</b> line item field{lineItemCount !== 1 ? "s" : ""} per row.</>
                  )}
                  {lineItemCount > 0 && (
                    <><br /><br />Multi-item invoices → <b>1 row per line item</b> with header fields repeated.</>
                  )}
                </>
              ) : (
                "Add columns to see extraction preview."
              )}
            </div>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}

// ─── Fallback editor (used while Univer loads or if install fails) ────────────
function FallbackEditor({
  columns, colTypes, selectedCol, onColumnsChange, onColumnSelect
}: {
  columns: TemplateColumn[];
  colTypes: Record<number, "header" | "lineitem">;
  selectedCol: number | null;
  onColumnsChange: (cols: TemplateColumn[]) => void;
  onColumnSelect: (idx: number) => void;
}) {
  const PREVIEW_ROWS = 7;
  const cols = columns.length > 0 ? columns : Array(8).fill(null).map((_, i) => ({ name: "", type: "Text" as const, order: i }));

  function updateName(i: number, v: string) {
    const next = [...cols];
    while (next.length <= i) next.push({ name: "", type: "Text", order: next.length });
    next[i] = { ...next[i], name: v };
    onColumnsChange(next);
  }

  function addCol() {
    onColumnsChange([...cols, { name: "", type: "Text", order: cols.length }]);
  }

  return (
    <div style={{ overflow: "auto", background: "#fff" }}>
      <table style={{ borderCollapse: "collapse", minWidth: "100%" }}>
        <thead>
          <tr>
            <th style={{ width: 40, background: "#f8f9fb", border: "1px solid #ddd", fontSize: 11, color: "#888" }}></th>
            {cols.map((_, i) => (
              <th
                key={i}
                onClick={() => onColumnSelect(i)}
                style={{
                  background: selectedCol === i ? "#c8d3ff" : "#f8f9fb",
                  border: "1px solid #ddd",
                  fontSize: 11, fontWeight: 500, color: "#555",
                  padding: "4px 8px", cursor: "pointer", minWidth: 120,
                }}
              >
                {String.fromCharCode(65 + i)}
              </th>
            ))}
            <th
              style={{ background: "#f8f9fb", border: "1px dashed #ddd", width: 36, cursor: "pointer", color: "#aaa", fontSize: 16 }}
              onClick={addCol}
            >+</th>
          </tr>
        </thead>
        <tbody>
          {/* Header row */}
          <tr>
            <td style={{ background: "#f8f9fb", border: "1px solid #ddd", textAlign: "center", fontSize: 11, color: "#888" }}>1</td>
            {cols.map((col, i) => {
              const t = colTypes[i] ?? "header";
              return (
                <td key={i} style={{ border: `1px solid ${selectedCol === i ? "#818cf8" : "#ddd"}`, background: t === "header" ? "#eff6ff" : "#f0fdf4", padding: 0 }}>
                  <input
                    style={{ width: "100%", height: 28, border: "none", outline: "none", padding: "0 8px", fontSize: 12, fontWeight: 600, background: "transparent", color: t === "header" ? "#1d4ed8" : "#15803d", fontFamily: "inherit" }}
                    value={col.name}
                    placeholder="Column name…"
                    onChange={e => updateName(i, e.target.value)}
                    onFocus={() => onColumnSelect(i)}
                  />
                </td>
              );
            })}
            <td style={{ border: "1px dashed #ddd" }} />
          </tr>
          {/* Preview rows */}
          {Array.from({ length: PREVIEW_ROWS }).map((_, r) => (
            <tr key={r}>
              <td style={{ background: "#f8f9fb", border: "1px solid #ddd", textAlign: "center", fontSize: 11, color: "#888" }}>{r + 2}</td>
              {cols.map((_, i) => (
                <td key={i} style={{ border: "1px solid #e8e8e8", padding: 0 }}>
                  <input
                    style={{ width: "100%", height: 24, border: "none", outline: "none", padding: "0 6px", fontSize: 12, background: "transparent", fontFamily: "inherit" }}
                    placeholder=""
                    onFocus={() => onColumnSelect(i)}
                  />
                </td>
              ))}
              <td style={{ border: "1px dashed #eee" }} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
