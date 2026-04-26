"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, CellValueChangedEvent } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-alpine.css";
import { extractApi, type DocumentResult, type ColumnTemplate } from "@/lib/api";
import toast from "react-hot-toast";

interface Props {
  results: DocumentResult[];
  jobId: number;
  template: ColumnTemplate | null;
}

export default function ResultsGrid({ results, jobId, template }: Props) {
  const gridRef = useRef<AgGridReact>(null);
  const [saving, setSaving] = useState(false);

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
      const row: Record<string, unknown> = {
        _id: doc.id,
        _filename: doc.filename,
        _confidence: doc.overall_confidence,
        _needs_review: doc.needs_review,
      };
      for (const key of fieldKeys) {
        const fd = ext[key];
        if (fd === undefined || fd === null) {
          row[key] = "";
        } else if (typeof fd === "object" && "value" in fd) {
          row[key] = (fd as any).value === null || (fd as any).value === undefined ? "" : (fd as any).value;
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
        width: 112,
        editable: false,
        cellRenderer: ({ value }: any) => {
          if (!value) return "";
          const cls = value === "high" ? "conf-high" : value === "medium" ? "conf-medium" : "conf-low";
          return `<span class="${cls}">${value}</span>`;
        },
      },
      {
        field: "_needs_review",
        headerName: "Status",
        width: 95,
        editable: false,
        cellRenderer: ({ value }: any) =>
          value
            ? `<span style="color:var(--amber);font-size:11px;font-weight:600">Review</span>`
            : `<span style="color:var(--green);font-size:11px">OK</span>`,
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
      updated.extracted_data[field] = { value: e.newValue ?? "", confidence: "high" };
      await extractApi.updateDocument(jobId, docId, updated);
      toast.success("Saved");
    } catch {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  }, [results, jobId]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text1)" }}>
            {results.length} document{results.length !== 1 ? "s" : ""}
            {template && <span style={{ fontSize: 12, color: "var(--text3)", marginLeft: 8, fontWeight: 400 }}>· {template.name}</span>}
          </div>
          <div style={{ fontSize: 11, color: "var(--text3)" }}>Click any cell to edit · changes save automatically</div>
        </div>
        {saving && (
          <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 11, color: "var(--text3)" }}>
            <svg className="animate-spin" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>
            Saving…
          </div>
        )}
      </div>
      <div className="ag-theme-alpine" style={{ height: 420, width: "100%" }}>
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
    </div>
  );
}
