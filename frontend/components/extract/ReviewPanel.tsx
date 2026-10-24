"use client";

// The review panel: one document record, its page image on one side and its
// values on the other. The image is the one the READER saw — the straightened
// image for an OCR'd page, the rendered page otherwise — and a selected value's
// box is drawn in that image's frame. A value with no box says why; nothing is
// guessed.
//
// Keyboard: j / ↓ next value needing review, k / ↑ previous, a accept (mark
// reviewed), e edit, Enter save, Esc cancel or close.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import toast from "react-hot-toast";
import { extractApi, reviewApi, type DocumentResult, type PageMeta } from "@/lib/api";
import {
  badgeFor, boxToPercent, reasonText, recordLabel, stepOpen,
  type ReasonMap, type ReviewDoc, type ReviewValue,
} from "@/lib/review";

interface Props {
  jobId: number;
  doc: ReviewDoc;
  result: DocumentResult | undefined;
  reasons: ReasonMap | undefined;
  onClose: () => void;
  onChanged: () => void;
}

export function Badge({ v }: { v: Pick<ReviewValue, "status" | "resolved" | "reviewed"> }) {
  const b = badgeFor(v);
  return (
    <span style={{ display: "inline-block", fontSize: 10.5, fontWeight: 600, lineHeight: "16px",
                   padding: "0 6px", borderRadius: 8, color: b.fg, background: b.bg,
                   whiteSpace: "nowrap" }}>
      {b.text}
    </span>
  );
}

function valueKey(v: ReviewValue) {
  return v.kind === "field" ? `f:${v.ref}` : `c:${v.table}:${v.row}:${v.column}`;
}

export default function ReviewPanel({ jobId, doc, result, reasons, onClose, onChanged }: Props) {
  const values = doc.values;
  const firstOpen = useMemo(() => stepOpen(values, -1, 1), [values]);
  const [sel, setSel] = useState<number>(firstOpen >= 0 ? firstOpen : 0);
  const [page, setPage] = useState<number>(values[sel]?.page ?? doc.pages[0] ?? 1);
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const [img, setImg] = useState<string | null>(null);
  const [imgError, setImgError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const current = values[sel];

  // the page follows the selected value (a page button can still move away)
  const selPage = current?.page ?? null;
  useEffect(() => {
    if (selPage) setPage(selPage);
  }, [sel, selPage]);

  useEffect(() => {
    let cancelled = false;
    let url: string | null = null;
    setLoading(true); setImgError(null); setMeta(null); setImg(null);
    Promise.all([reviewApi.page(jobId, doc.doc_id, page),
                 reviewApi.pageImageUrl(jobId, doc.doc_id, page)])
      .then(([m, u]) => {
        url = u;
        if (cancelled) { URL.revokeObjectURL(u); return; }
        setMeta(m); setImg(u);
      })
      .catch((e: any) => {
        if (!cancelled) setImgError(e?.response?.status === 404
          ? "This page is not available (the source document is not retained)."
          : "The page could not be loaded.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [jobId, doc.doc_id, page]);

  const boxFor = useCallback((v: ReviewValue | undefined) => {
    if (!v || !meta) return undefined;
    return meta.boxes.find(b => (v.kind === "field" ? b.ref === v.ref
      : b.table === v.table && b.row === v.row && b.column === v.column));
  }, [meta]);

  const accept = useCallback(async (v: ReviewValue | undefined) => {
    if (!v || busy) return;
    setBusy(true);
    try {
      await reviewApi.mark(jobId, doc.doc_id, {
        values: [v.kind === "field" ? { ref: String(v.ref) }
                                    : { table: String(v.table), row: Number(v.row) }],
      });
      toast.success("Marked reviewed");
      onChanged();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? "Could not save the review mark");
    } finally { setBusy(false); }
  }, [busy, jobId, doc.doc_id, onChanged]);

  const save = useCallback(async (v: ReviewValue, text: string) => {
    setBusy(true);
    try {
      let saved: { extracted_data: Record<string, any> };
      if (v.kind === "field" && v.ref) {
        saved = await extractApi.editField(jobId, doc.doc_id, v.ref, text);
      } else if (result?.extracted_data && v.table != null && v.row != null && v.column) {
        const ed = JSON.parse(JSON.stringify(result.extracted_data));
        const rows = ed[`${v.table}_rows`];
        if (!Array.isArray(rows) || !rows[v.row]) throw new Error("row not found");
        rows[v.row][v.column] = text;
        saved = await extractApi.updateDocument(jobId, doc.doc_id, ed);
      } else {
        throw new Error("This value cannot be edited here");
      }
      // keep the grid's copy current, as the grid's own edits do
      if (result) result.extracted_data = saved.extracted_data as DocumentResult["extracted_data"];
      toast.success("Saved — marked as edited");
      setEditing(null);
      onChanged();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail ?? e?.message ?? "Save failed");
    } finally { setBusy(false); }
  }, [jobId, doc.doc_id, result, onChanged]);

  const markDocument = useCallback(async () => {
    setBusy(true);
    try {
      await reviewApi.mark(jobId, doc.doc_id, { scope: "document" });
      toast.success("Document marked reviewed");
      onChanged();
    } catch { toast.error("Could not save the review mark"); }
    finally { setBusy(false); }
  }, [jobId, doc.doc_id, onChanged]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA");
      if (e.key === "Escape") {
        if (editing !== null) setEditing(null); else onClose();
        return;
      }
      if (typing) return;
      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        const n = stepOpen(values, sel, 1); if (n >= 0) setSel(n);
      } else if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        const n = stepOpen(values, sel, -1); if (n >= 0) setSel(n);
      } else if (e.key === "a") {
        e.preventDefault(); accept(current);
      } else if (e.key === "e" && current) {
        e.preventDefault(); setEditing(String(current.value ?? ""));
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [values, sel, current, editing, accept, onClose]);

  useEffect(() => {
    listRef.current?.querySelector(`[data-idx="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const selBox = boxFor(current);
  const pages = doc.pages.length ? doc.pages : [1];

  return (
    <div role="dialog" aria-modal="true" aria-label={`Review ${doc.filename}`}
         style={{ position: "fixed", inset: 0, zIndex: 50, background: "rgba(15,23,42,0.45)",
                  display: "flex", alignItems: "stretch", justifyContent: "center", padding: 16 }}
         onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="card review-panel"
           style={{ width: "min(1280px, 100%)", display: "flex", flexDirection: "column",
                    padding: 0, overflow: "hidden" }}>
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                      borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text1)" }}>
              {recordLabel(doc)}
            </div>
            <div style={{ fontSize: 11, color: "var(--text3)" }}>
              {doc.summary.needs_review
                ? `${doc.summary.needs_review} value${doc.summary.needs_review === 1 ? "" : "s"} need review`
                : "Nothing in this document needs review"}
              {" · "}j/k next/previous · a accept · e edit · Esc close
            </div>
          </div>
          <button className="btn btn-secondary btn-sm" onClick={markDocument}
                  disabled={busy || doc.document_reviewed}>
            {doc.document_reviewed ? "Document reviewed" : "Mark document reviewed"}
          </button>
          <button className="btn btn-secondary btn-sm" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="review-body" style={{ flex: 1, minHeight: 0, display: "grid",
                      gridTemplateColumns: "minmax(0,3fr) minmax(300px,2fr)" }}>
          {/* image */}
          <div style={{ overflow: "auto", background: "var(--surface2)", padding: 12,
                        borderRight: "1px solid var(--border)" }}>
            {pages.length > 1 && (
              <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
                {pages.map(p => (
                  <button key={p} className={`btn btn-sm ${p === page ? "btn-primary" : "btn-secondary"}`}
                          onClick={() => setPage(p)}>Page {p}</button>
                ))}
              </div>
            )}
            {loading && <p style={{ fontSize: 12, color: "var(--text3)" }}>Loading page {page}…</p>}
            {imgError && <p role="alert" style={{ fontSize: 12, color: "var(--red)" }}>{imgError}</p>}
            {img && meta && (
              <>
                <div style={{ fontSize: 11, color: "var(--text3)", marginBottom: 6 }}>
                  Page {page} · {meta.origin === "ocr" ? "scan, as straightened for OCR"
                                  : meta.origin === "pre_ocr" ? "scan with an embedded OCR layer"
                                  : "digital page"}
                </div>
                <div style={{ position: "relative", width: "100%" }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={img} alt={`Page ${page} of ${doc.filename}`}
                       style={{ width: "100%", display: "block", border: "1px solid var(--border)" }}/>
                  {meta.width_pt && meta.height_pt && meta.record_box_pt && (
                    <div aria-hidden style={{ position: "absolute",
                         ...boxToPercent(meta.record_box_pt, meta.width_pt, meta.height_pt),
                         border: "2px dashed #6366f1" }}/>
                  )}
                  {meta.width_pt && meta.height_pt && selBox?.box_pt && (
                    <div aria-hidden style={{ position: "absolute",
                         ...boxToPercent(selBox.box_pt, meta.width_pt, meta.height_pt),
                         outline: "3px solid #dc2626", background: "rgba(220,38,38,0.12)" }}/>
                  )}
                </div>
              </>
            )}
          </div>

          {/* values */}
          <div ref={listRef} style={{ overflow: "auto", padding: 8 }}>
            {doc.failed && (
              <p role="alert" style={{ fontSize: 12, color: "var(--red)", padding: 8 }}>
                Extraction failed for this document{doc.error ? `: ${doc.error}` : ""}. Nothing was extracted.
              </p>
            )}
            {!values.length && !doc.failed && (
              <p style={{ fontSize: 12, color: "var(--text3)", padding: 8 }}>No values.</p>
            )}
            {values.map((v, i) => {
              const active = i === sel;
              const b = active ? selBox : undefined;
              return (
                <div key={valueKey(v)} data-idx={i}
                     onClick={() => { setSel(i); setEditing(null); }}
                     style={{ padding: "6px 8px", borderRadius: 6, cursor: "pointer",
                              background: active ? "var(--surface2)" : "transparent",
                              outline: active ? "2px solid var(--accent)" : "none",
                              marginBottom: 2 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ flex: 1, fontSize: 11, color: "var(--text3)" }}>{v.label}</span>
                    <Badge v={v}/>
                  </div>
                  {active && editing !== null ? (
                    <form onSubmit={e => { e.preventDefault(); save(v, editing); }}
                          style={{ display: "flex", gap: 6, marginTop: 4 }}>
                      <input className="input" autoFocus value={editing} aria-label={`Edit ${v.label}`}
                             onChange={e => setEditing(e.target.value)} style={{ flex: 1 }}/>
                      <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>Save</button>
                    </form>
                  ) : (
                    <div style={{ fontSize: 13, color: "var(--text1)", wordBreak: "break-word" }}>
                      {String(v.value ?? "") || <em style={{ color: "var(--text3)" }}>empty</em>}
                    </div>
                  )}
                  {v.reasons.length > 0 && (
                    <ul style={{ margin: "4px 0 0", paddingLeft: 16 }}>
                      {v.reasons.map(code => {
                        const r = reasonText(code, reasons);
                        return (
                          <li key={code} title={r.tooltip} style={{ fontSize: 11, color: "var(--text2)" }}>
                            {r.label}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  {active && (
                    <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
                      {!v.resolved && (
                        <button className="btn btn-secondary btn-sm" disabled={busy}
                                onClick={e => { e.stopPropagation(); accept(v); }}>Accept (a)</button>
                      )}
                      {editing === null && (
                        <button className="btn btn-secondary btn-sm" disabled={busy}
                                onClick={e => { e.stopPropagation(); setEditing(String(v.value ?? "")); }}>
                          Edit (e)
                        </button>
                      )}
                      <span style={{ fontSize: 10.5, color: "var(--text3)" }}>
                        {!v.page ? "No page recorded for this value, so no box."
                          : !meta ? ""
                          : b?.box_pt ? (b.match === "line" ? "Box: the line it was read from" : "Box: the value")
                          : `No box: ${b?.no_box_reason ?? "the value is not on this page"}.`}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <style>{`
        @media (max-width: 900px) {
          .review-panel .review-body { grid-template-columns: 1fr !important; grid-template-rows: minmax(240px, 45%) 1fr; }
        }
      `}</style>
    </div>
  );
}
