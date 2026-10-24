"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AgGridReact } from "ag-grid-react";
import type { ColDef, CellValueChangedEvent, ICellRendererParams } from "ag-grid-community";
import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-alpine.css";
import { extractApi, reviewApi, type DocumentResult, type ColumnTemplate } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import {
  FILTERS, fieldsByLabel, matches, reasonText, recordLabel,
  type Filter, type ReviewDoc, type ReviewValue,
} from "@/lib/review";
import ReviewPanel, { Badge } from "@/components/extract/ReviewPanel";
import toast from "react-hot-toast";

interface Props {
  results: DocumentResult[];
  jobId: number;
  template: ColumnTemplate | null;
}

// ── Cell renderers (React components, no innerHTML) ───────────────────────────

// The DOCUMENT-level confidence vocabulary. Mirrors backend/app/core/
// confidence.py — read that module's docstring before changing a word here.
// Per-value review status comes from the server (app/core/review.py) and is
// drawn by <Badge>.
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

function StatusCell({ value, data }: ICellRendererParams) {
  const open = (data?._open as number) ?? 0;
  const needs = Boolean(value) || open > 0;
  return (
    <span style={{
      fontSize: 11, fontWeight: 600,
      color: needs ? "var(--amber,#b45309)" : "var(--green,#15803d)",
    }}>
      {needs ? (open ? `Review (${open})` : "Review") : "OK"}
    </span>
  );
}

// ── Table rows sub-panel ──────────────────────────────────────────────────────

function TableRowsPanel({ rows }: { rows: Record<string, any>[] }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]).filter(c => !c.startsWith("_"));
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
  const qc = useQueryClient();
  // Presentation only, as everywhere else: the server decides who is a demo.
  const isDemo = useAuthStore(st => st.user?.is_demo === true);
  const [saving, setSaving] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [reviewId, setReviewId] = useState<number | null>(null);

  const review = useQuery({
    queryKey: ["review", jobId],
    queryFn: () => reviewApi.job(jobId),
    enabled: Number.isFinite(jobId),
  });
  const reasonsQ = useQuery({
    queryKey: ["review-reasons"],
    queryFn: reviewApi.reasons,
    staleTime: Infinity,
  });
  const reasons = reasonsQ.data?.reasons;
  const reviewDocs = useMemo(() => {
    const m = new Map<number, ReviewDoc>();
    for (const d of review.data?.documents ?? []) m.set(d.doc_id, d);
    return m;
  }, [review.data]);

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["review", jobId] });
  }, [qc, jobId]);

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

    const shown = results.filter(doc => {
      const rd = reviewDocs.get(doc.id);
      return !rd || matches(rd, filter);
    });

    const rows = shown.map(doc => {
      const ext = doc.extracted_data?.extracted_data ?? {};
      const tableRows = doc.extracted_data?.table_rows ?? [];
      const rd = reviewDocs.get(doc.id);
      const row: Record<string, unknown> = {
        _id:           doc.id,
        _filename:     rd ? recordLabel(rd) : doc.filename,
        _confidence:   doc.overall_confidence,
        _needs_review: doc.needs_review,
        _open:         rd?.summary.needs_review ?? 0,
        _table_rows:   tableRows,
        _has_rows:     tableRows.length > 0,
        _review:       rd ? fieldsByLabel(rd) : {},
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

    // The File column shows the record's name ("batch.pdf [2 of 3]") and its
    // pages. A demo audience sees neither: for a document that went to the
    // object store the stored name is a temp name, and the demo's exports
    // drop it for the same reason.
    const fixed: ColDef[] = [
      ...(isDemo ? [] : [{
        field: "_filename",
        headerName: "File · page",
        pinned: "left" as const,
        width: 210,
        editable: false,
        cellStyle: { fontWeight: 500, color: "var(--text1)" },
      }]),
      {
        field: "_needs_review",
        headerName: "Status",
        width: 105,
        editable: false,
        cellRenderer: StatusCell,
      },
      {
        field: "_confidence",
        headerName: "Confidence",
        width: 190,   // fits "Verbatim from the document" without truncating
        editable: false,
        cellRenderer: ConfidenceCell,
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
      minWidth: 190,
      cellStyle: { color: "var(--text1)" },
      valueFormatter: ({ value }: any) =>
        value === null || value === undefined ? "" : String(value),
      cellRenderer: ({ value, data }: ICellRendererParams) => {
        const rv = (data?._review as Record<string, ReviewValue> | undefined)?.[key];
        const text = value === null || value === undefined ? "" : String(value);
        if (!rv) return <span>{text}</span>;
        const why = rv.reasons.map(c => reasonText(c, reasons).label).join(" · ");
        return (
          <span title={why || undefined}
                style={{ display: "inline-flex", gap: 6, alignItems: "center", maxWidth: "100%" }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{text}</span>
            <Badge v={rv}/>
          </span>
        );
      },
    }));

    return { rowData: rows, colDefs: [...fixed, ...dynamic] };
  }, [results, template, isDemo, reviewDocs, filter, reasons]);

  const onCellValueChanged = useCallback(async (e: CellValueChangedEvent) => {
    const row = e.data as Record<string, unknown>;
    const docId = row._id as number;
    const field = e.colDef.field as string;
    if (!field || field.startsWith("_")) return;
    const doc = results.find(d => d.id === docId);
    if (!doc) return;
    setSaving(true);
    try {
      // An edit names a SLOT. The column is a label, and two slots can share a
      // label, so the cell reference carried on the entry is what is sent —
      // and the server moves every copy of the value together, so the download
      // holds what was typed. The server marks it "edited": a human typed it,
      // and it must not inherit a grounding claim.
      const value = e.newValue == null ? "" : String(e.newValue);
      const entry = (doc.extracted_data?.extracted_data ?? {})[field];
      const ref = entry && typeof entry === "object" ? entry.ref : undefined;
      let saved: { extracted_data: Record<string, any> };
      if (ref) {
        saved = await extractApi.editField(jobId, docId, ref, value);
      } else {
        // A document with no slot addresses (extracted before them): the
        // server resolves the label, and refuses one that names two cells.
        const updated = JSON.parse(JSON.stringify(doc.extracted_data ?? {}));
        if (!updated.extracted_data) updated.extracted_data = {};
        updated.extracted_data[field] = { value, confidence: "edited" };
        saved = await extractApi.updateDocument(jobId, docId, updated);
      }
      // Keep this copy current. Every save used to be built from the copy the
      // grid was first given, so a second edit silently reverted the first.
      doc.extracted_data = saved.extracted_data as DocumentResult["extracted_data"];
      toast.success("Saved");
      refresh();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? "Save failed");
    } finally {
      setSaving(false);
    }
  }, [results, jobId, refresh]);

  // Find expanded document's table rows
  const expandedDoc = expandedId != null
    ? results.find(r => r.id === expandedId)
    : null;
  const expandedRows = expandedDoc?.extracted_data?.table_rows ?? [];
  const s = review.data?.summary;
  const reviewDoc = reviewId != null ? reviewDocs.get(reviewId) : undefined;

  return (
    <div>
      {/* Header: counts, then filters */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 220 }}>
          <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text1)" }}>
            {results.length} document{results.length !== 1 ? "s" : ""}
            {s && (
              <span style={{ fontSize: 12, marginLeft: 8, fontWeight: 400,
                             color: s.needs_review ? "var(--amber,#b45309)" : "var(--green,#15803d)" }}>
                · {s.needs_review
                    ? `${s.needs_review} value${s.needs_review === 1 ? "" : "s"} need review, ${s.low} low`
                    : "nothing needs review"}
              </span>
            )}
            {template && (
              <span style={{ fontSize: 12, color: "var(--text3)", marginLeft: 8, fontWeight: 400 }}>
                · {template.name}
              </span>
            )}
          </div>
          <div style={{ fontSize: 11, color: "var(--text3)" }}>
            Click a row to review it against the page · double-click a cell to edit
            {results.some(r => (r.extracted_data?.table_rows?.length ?? 0) > 0) && (
              <span style={{ marginLeft: 8, color: "var(--accent)" }}>
                · Click row count to expand line items
              </span>
            )}
          </div>
          {review.isLoading && (
            <div style={{ fontSize: 11, color: "var(--text3)" }}>Loading review status…</div>
          )}
          {review.isError && (
            <div role="alert" style={{ fontSize: 11, color: "var(--red)" }}>
              Review status could not be loaded; values are shown without it.
            </div>
          )}
        </div>
        <div role="group" aria-label="Filter documents" style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {FILTERS.map(f => (
            <button key={f.id} type="button" aria-pressed={filter === f.id}
                    className={`btn btn-sm ${filter === f.id ? "btn-primary" : "btn-secondary"}`}
                    onClick={() => setFilter(f.id)}>
              {f.label}
            </button>
          ))}
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

      {/* AG Grid — paginated, so a day's 50 cheques stay responsive */}
      <div className="ag-theme-alpine" style={{ height: 460, width: "100%" }}>
        <AgGridReact
          ref={gridRef}
          rowData={rowData}
          columnDefs={colDefs}
          defaultColDef={{ sortable: true, resizable: true, filter: true }}
          onCellValueChanged={onCellValueChanged}
          onRowClicked={e => {
            const col = (e.event?.target as HTMLElement | null)?.closest?.("[col-id]")
              ?.getAttribute("col-id");
            if (col === "_has_rows") return;
            setReviewId((e.data?._id as number | undefined) ?? null);
          }}
          pagination
          paginationPageSize={25}
          paginationPageSizeSelector={[25, 50, 100]}
          animateRows
          getRowId={p => String(p.data._id)}
          overlayNoRowsTemplate={filter === "all" ? "No documents" : "No documents match this filter"}
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
              aria-label="Close line items"
              style={{ background: "none", border: "none", cursor: "pointer",
                color: "var(--text3)", fontSize: 18, lineHeight: 1 }}
            >
              ×
            </button>
          </div>
          <TableRowsPanel rows={expandedRows} />
        </div>
      )}

      {reviewDoc && (
        <ReviewPanel
          key={reviewDoc.doc_id}
          jobId={jobId}
          doc={reviewDoc}
          result={results.find(r => r.id === reviewDoc.doc_id)}
          reasons={reasons}
          onClose={() => setReviewId(null)}
          onChanged={refresh}
        />
      )}
    </div>
  );
}
