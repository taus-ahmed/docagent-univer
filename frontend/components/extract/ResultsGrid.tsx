"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, CellValueChangedEvent, ICellRendererParams } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-alpine.css";
import { extractApi, type DocumentResult, type ColumnTemplate } from "@/lib/api";
import toast from "react-hot-toast";

interface Props {
  results: DocumentResult[];
  jobId: number;
  template: ColumnTemplate | null;
}

// ── Cell renderers (React components, no innerHTML) ───────────────────────────

// The confidence vocabulary. Mirrors backend/app/core/confidence.py — read
// that module's docstring before changing a word here. In short:
//   high       grounded in the document AND the user authored the slot label
//   grounded   grounded, but the MODEL named the slot, so nothing independent
//              says the value belongs there (no-template extraction)
//   unverified no text layer existed to check any span against (image upload)
//   low        checked and failed
const CONFIDENCE_LABEL: Record<string, string> = {
  high:       "High",
  grounded:   "Verbatim from the document",
  unverified: "Unverified — no text layer",
  medium:     "Medium",
  low:        "Low",
  edited:     "Edited by hand",
};

const CONFIDENCE_COLOR: Record<string, string> = {
  high:       "var(--green,#22c55e)",
  grounded:   "var(--blue,#2563eb)",   // confident, but a DIFFERENT claim from high
  unverified: "var(--text3,#6b7280)",  // not a judgement — nothing was measured
  medium:     "var(--amber,#f59e0b)",
  low:        "var(--red,#ef4444)",
  edited:     "var(--accent,#4f46e5)",
};

function ConfidenceCell({ value }: ICellRendererParams) {
  if (!value) return null;
  const key = String(value);
  return (
    <span
      title={CONFIDENCE_LABEL[key] ?? key}
      style={{
        fontSize: 11, fontWeight: 600,
        color: CONFIDENCE_COLOR[key] ?? "var(--text3)",
      }}
    >
      {CONFIDENCE_LABEL[key] ?? key}
    </span>
  );
}

function StatusCell({ value }: ICellRendererParams) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 600,
      color: value ? "var(--amber,#f59e0b)" : "var(--green,#22c55e)",
    }}>
      {value ? "Review" : "OK"}
    </span>
  );
}

// ── Table rows sub-panel ──────────────────────────────────────────────────────

function TableRowsPanel({ rows }: { rows: Record<string, any>[] }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div style={{ marginTop: 10, overflowX: "auto" }}>
      <p style={{ fontSize: 11, color: "var(--text3)", marginBottom: 6 }}>
        {rows.length} line item{rows.length !== 1 ? "s" : ""}
      </p>
      <table style={{ borderCollapse: "collapse", fontSize: 11, width: "100%" }}>
        <thead>
          <tr>
            {cols.map(c => (
              <th key={c} style={{
                padding: "4px 8px", textAlign: "left",
                borderBottom: "1px solid var(--border)",
                color: "var(--text3)", fontWeight: 600, whiteSpace: "nowrap",
              }}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? "var(--surface2)" : "transparent" }}>
              {cols.map(c => (
                <td key={c} style={{
                  padding: "4px 8px",
                  borderBottom: "1px solid var(--border)",
                  color: "var(--text2)",
                  whiteSpace: "nowrap",
                }}>
                  {String(row[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Main grid ─────────────────────────────────────────────────────────────────

export default function ResultsGrid({ results, jobId, template }: Props) {
  const gridRef = useRef<AgGridReact>(null);
  const [saving, setSaving] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const { rowData, colDefs } = useMemo(() => {
    const templateCols = template?.columns ?? null;

    let fieldKeys: string[];
    if (templateCols && templateCols.length > 0) {
      fieldKeys = [...templateCols].sort((a, b) => a.order - b.order).map(c => c.name);
    } else {
      const keys = new Set<string>();
      for (const doc of results) {
        const ext = doc.extracted_data?.extracted_data ?? {};
        Object.keys(ext).forEach(k => keys.add(k));
      }
      fieldKeys = Array.from(keys);
    }

    const rows = results.map(doc => {
      const ext = doc.extracted_data?.extracted_data ?? {};
      const tableRows = doc.extracted_data?.table_rows ?? [];
      const row: Record<string, unknown> = {
        _id:           doc.id,
        _filename:     doc.filename,
        _confidence:   doc.overall_confidence,
        _needs_review: doc.needs_review,
        _table_rows:   tableRows,
        _has_rows:     tableRows.length > 0,
      };
      for (const key of fieldKeys) {
        const fd = ext[key];
        if (fd === undefined || fd === null) {
          row[key] = "";
        } else if (typeof fd === "object" && "value" in fd) {
          row[key] = (fd as any).value ?? "";
        } else {
          row[key] = fd;
        }
      }
      return row;
    });

    const fixed: ColDef[] = [
      {
        field: "_filename",
        headerName: "File",
        pinned: "left",
        width: 170,
        editable: false,
        cellStyle: { fontWeight: 500, color: "var(--text1)" },
      },
      {
        field: "_confidence",
        headerName: "Confidence",
        width: 190,   // fits "Verbatim from the document" without truncating

        editable: false,
        cellRenderer: ConfidenceCell,
      },
      {
        field: "_needs_review",
        headerName: "Status",
        width: 95,
        editable: false,
        cellRenderer: StatusCell,
      },
      {
        field: "_has_rows",
        headerName: "Rows",
        width: 70,
        editable: false,
        cellRenderer: ({ value, data }: ICellRendererParams) =>
          value ? (
            <span style={{ fontSize: 11, color: "var(--accent)", cursor: "pointer" }}>
              {(data._table_rows as any[]).length}
            </span>
          ) : null,
        onCellClicked: ({ data }: any) => {
          if (data._has_rows) {
            setExpandedId(prev => prev === data._id ? null : data._id);
          }
        },
      },
    ];

    const dynamic: ColDef[] = fieldKeys.map(key => ({
      field: key,
      headerName: key,
      editable: true,
      flex: 1,
      minWidth: 120,
      cellStyle: { color: "var(--text1)" },
      valueFormatter: ({ value }: any) =>
        value === null || value === undefined ? "" : String(value),
    }));

    return { rowData: rows, colDefs: [...fixed, ...dynamic] };
  }, [results, template]);

  const onCellValueChanged = useCallback(async (e: CellValueChangedEvent) => {
    const row = e.data as Record<string, unknown>;
    const docId = row._id as number;
    const field = e.colDef.field as string;
    if (!field || field.startsWith("_")) return;
    const doc = results.find(d => d.id === docId);
    if (!doc) return;
    setSaving(true);
    try {
      const updated = JSON.parse(JSON.stringify(doc.extracted_data ?? {}));
      if (!updated.extracted_data) updated.extracted_data = {};
      // A human typed this. It is not a grounded extraction and must not
      // inherit a grounding claim — "high" here would assert the engine
      // verified a value the engine never saw.
      updated.extracted_data[field] = { value: e.newValue ?? "", confidence: "edited" };
      await extractApi.updateDocument(jobId, docId, updated);
      toast.success("Saved");
    } catch {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  }, [results, jobId]);

  // Find expanded document's table rows
  const expandedDoc = expandedId != null
    ? results.find(r => r.id === expandedId)
    : null;
  const expandedRows = expandedDoc?.extracted_data?.table_rows ?? [];

  return (
    <div>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text1)" }}>
            {results.length} document{results.length !== 1 ? "s" : ""}
            {template && (
              <span style={{ fontSize: 12, color: "var(--text3)", marginLeft: 8, fontWeight: 400 }}>
                · {template.name}
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "var(--text3)" }}>
            Click any cell to edit · changes save automatically
            {results.some(r => (r.extracted_data?.table_rows?.length ?? 0) > 0) && (
              <span style={{ marginLeft: 8, color: "var(--accent)" }}>
                · Click row count to expand line items
              </span>
            )}
          </div>
        </div>
        {saving && (
          <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--text3)" }}>
            <svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24"
              fill="none" stroke="var(--accent)" strokeWidth="2">
              <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
            </svg>
            Saving...
          </div>
        )}
      </div>

      {/* AG Grid */}
      <div className="ag-theme-alpine" style={{ height: 380, width: "100%" }}>
        <AgGridReact
          ref={gridRef}
          rowData={rowData}
          columnDefs={colDefs}
          defaultColDef={{ sortable: true, resizable: true, filter: true }}
          onCellValueChanged={onCellValueChanged}
          animateRows
          getRowId={p => String(p.data._id)}
        />
      </div>

      {/* Expandable table rows panel */}
      {expandedDoc && expandedRows.length > 0 && (
        <div className="card" style={{ marginTop: 12, padding: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text1)" }}>
              {expandedDoc.filename} — Line Items
            </span>
            <button
              onClick={() => setExpandedId(null)}
              style={{ background: "none", border: "none", cursor: "pointer",
                color: "var(--text3)", fontSize: 18, lineHeight: 1 }}
            >
              ×
            </button>
          </div>
          <TableRowsPanel rows={expandedRows} />
        </div>
      )}
    </div>
  );
}
