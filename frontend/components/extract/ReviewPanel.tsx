"use client";

// The review panel: one document record, its page image on one side and its
// values on the other. The image is the one the READER saw — the straightened
// image for an OCR'd page, the rendered page otherwise — and a selected value's
// box is drawn in that image's frame. A value with no box says why; nothing is
// guessed.
//
// Keyboard: j / ↓ next value needing review, k / ↑ previous; on a flagged
// value a accept as is, c correct, m mark empty; e edit any value; Enter
// save, Esc cancel or close.
//
// Run G, G5: a flagged value offers three explicit actions (Accept as is,
// Correct, Mark empty) and each is ONE request (lib/reviewActions.ts). A table
// can take a row the extraction missed (Add row), and the History panel reads
// the document's append-only history.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import toast from "react-hot-toast";
import { extractApi, reviewApi, type DocumentResult, type PageMeta } from "@/lib/api";
import {
  badgeFor, boxToPercent, detailText, locationNotFound, reasonText, recordLabel, stepOpen,
  type AttentionItem, type ReasonMap, type ReviewDoc, type ReviewValue,
} from "@/lib/review";
import {
  actionDone, actionsFor, addRowBody, historyLine, reviewBody, tablesOf, valueEntry,
  type HistoryEvent, type ValueDisposition,
} from "@/lib/reviewActions";

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
  /** "correct" = the typed text replaces the value AND accepts it (one
   *  request); "edit" = a plain edit of a value that owes nothing. */
  const [editMode, setEditMode] = useState<"correct" | "edit">("edit");
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<HistoryEvent[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const tables = useMemo(() => tablesOf(result?.extracted_data), [result]);
  const [addTable, setAddTable] = useState<string | null>(null);
  const [addValues, setAddValues] = useState<Record<string, string>>({});
  const [addReason, setAddReason] = useState<string>("");
  const listRef = useRef<HTMLDivElement>(null);
  const current = values[sel];
  const openAttention = (doc.attention ?? []).filter(a => !a.disposition);

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

  const loadHistory = useCallback(async () => {
    setHistoryError(null);
    try {
      setHistory((await reviewApi.history(jobId, doc.doc_id)).events);
    } catch (e: any) {
      setHistoryError(detailText(e, "The history could not be loaded"));
    }
  }, [jobId, doc.doc_id]);

  const changed = useCallback(() => {
    onChanged();
    if (showHistory) loadHistory();
  }, [onChanged, showHistory, loadHistory]);

  /** Accept as is / Correct / Mark empty: one request each. */
  const dispose = useCallback(async (v: ReviewValue | undefined, d: ValueDisposition,
                                     value?: string) => {
    if (!v || busy) return;
    let body;
    try {
      body = reviewBody([valueEntry(v, d, value)]);
    } catch (e: any) {
      toast.error(e?.message ?? "This value cannot be reviewed here");
      return;
    }
    setBusy(true);
    try {
      await reviewApi.mark(jobId, doc.doc_id, body);
      toast.success(actionDone(d));
      setEditing(null);
      changed();
    } catch (e: any) {
      toast.error(`Not saved: ${detailText(e, "Could not save the review mark")}`);
    } finally { setBusy(false); }
  }, [busy, jobId, doc.doc_id, changed]);

  const accept = useCallback((v: ReviewValue | undefined) => {
    if (v && !v.resolved) dispose(v, "accepted_as_is");
  }, [dispose]);

  const startEdit = useCallback((v: ReviewValue | undefined, mode: "correct" | "edit") => {
    if (!v) return;
    setEditMode(mode);
    setEditing(String(v.value ?? ""));
  }, []);

  const addRow = useCallback(async () => {
    const spec = tables.find(t => t.name === addTable);
    if (!spec) return;
    const body = addRowBody(spec, addValues, addReason || null);
    if (!body) { toast.error("Type at least one value for the new row"); return; }
    setBusy(true);
    try {
      const r = await reviewApi.addRow(jobId, doc.doc_id, spec.name, body);
      toast.success(r.reflagged_totals.length
        ? `Row added — check ${r.reflagged_totals.join(", ")}: the total no longer matches`
        : "Row added");
      setAddTable(null); setAddValues({}); setAddReason("");
      changed();
    } catch (e: any) {
      toast.error(`Not added: ${detailText(e, "Could not add the row")}`);
    } finally { setBusy(false); }
  }, [tables, addTable, addValues, addReason, jobId, doc.doc_id, changed]);

  const save = useCallback(async (v: ReviewValue, text: string) => {
    setBusy(true);
    try {
      let saved: { extracted_data: Record<string, any> };
      if (v.kind === "field" && v.ref) {
        saved = await extractApi.editField(jobId, doc.doc_id, v.ref, text);
      } else if (v.table != null && v.row != null && v.column) {
        // ONE cell, changed on the server's stored copy. Sending this page's
        // whole copy back used to undo every review mark made since it was
        // loaded — "I edit, save, accept, and the change does not stick".
        saved = await extractApi.editCell(jobId, doc.doc_id, String(v.table),
                                          Number(v.row), String(v.column), text);
      } else {
        throw new Error("This value cannot be edited here");
      }
      // keep the grid's copy current, as the grid's own edits do
      if (result) result.extracted_data = saved.extracted_data as DocumentResult["extracted_data"];
      toast.success("Saved — marked as edited");
      setEditing(null);
      changed();
    } catch (e: any) {
      toast.error(`Not saved: ${detailText(e, "Save failed")}`);
    } finally { setBusy(false); }
  }, [jobId, doc.doc_id, result, changed]);

  const submitEdit = useCallback((v: ReviewValue, text: string) => {
    if (editMode === "correct") dispose(v, "corrected", text);
    else save(v, text);
  }, [editMode, dispose, save]);

  useEffect(() => {
    if (showHistory) loadHistory();
  }, [showHistory, loadHistory]);

  const settle = useCallback(async (a: AttentionItem,
                                    choice: "confirmed_absent" | "entered_manually") => {
    setBusy(true);
    try {
      await reviewApi.mark(jobId, doc.doc_id, { dispositions: [{ id: a.id, choice }] });
      toast.success(choice === "confirmed_absent" ? "Recorded: confirmed absent"
                                                  : "Recorded: entered by hand");
      onChanged();
    } catch (e: any) {
      toast.error(`Not saved: ${detailText(e, "Could not record the decision")}`);
    } finally { setBusy(false); }
  }, [jobId, doc.doc_id, onChanged]);

  const markDocument = useCallback(async () => {
    setBusy(true);
    try {
      await reviewApi.mark(jobId, doc.doc_id, { scope: "document" });
      toast.success("Document marked reviewed");
      onChanged();
    } catch (e: any) {
      // 409 while a completeness reason is open: the server names them
      toast.error(detailText(e, "Could not save the review mark"));
    }
    finally { setBusy(false); }
  }, [jobId, doc.doc_id, onChanged]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
                           || t.tagName === "SELECT");
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
      } else if (e.key === "c" && current && !current.resolved) {
        e.preventDefault(); startEdit(current, "correct");
      } else if (e.key === "m" && current && actionsFor(current).length) {
        e.preventDefault(); dispose(current, "confirmed_empty");
      } else if (e.key === "e" && current) {
        e.preventDefault(); startEdit(current, current.resolved ? "edit" : "correct");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [values, sel, current, editing, accept, dispose, startEdit, onClose]);

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
              {openAttention.length
                ? `NEEDS ATTENTION — ${openAttention.length} completeness reason${openAttention.length === 1 ? "" : "s"} open · `
                : ""}
              {doc.summary.needs_review
                ? `${doc.summary.needs_review} value${doc.summary.needs_review === 1 ? "" : "s"} need review`
                : openAttention.length ? "no value needs review"
                : "Nothing in this document needs review"}
              {" · "}j/k next/previous · a accept · c correct · m mark empty · e edit · Esc close
            </div>
          </div>
          <button className="btn btn-secondary btn-sm" aria-pressed={showHistory}
                  onClick={() => setShowHistory(s => !s)}>
            {showHistory ? "Hide history" : "History"}
          </button>
          <button className="btn btn-secondary btn-sm" onClick={markDocument}
                  title={openAttention.length ? "Settle each completeness reason first" : undefined}
                  disabled={busy || doc.document_reviewed || openAttention.length > 0}>
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
            {showHistory && (
              <div role="region" aria-label="History"
                   style={{ border: "1px solid var(--border)", borderRadius: 6, padding: 8,
                            marginBottom: 8, background: "var(--surface2)" }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text1)", marginBottom: 4 }}>
                  History (read-only)
                </div>
                {historyError && <p role="alert" style={{ fontSize: 11, color: "var(--red)" }}>{historyError}</p>}
                {!historyError && history === null && (
                  <p style={{ fontSize: 11, color: "var(--text3)" }}>Loading history…</p>
                )}
                {history !== null && history.length === 0 && (
                  <p style={{ fontSize: 11, color: "var(--text3)" }}>Nothing has been changed or reviewed yet.</p>
                )}
                {history !== null && history.length > 0 && (
                  <ol style={{ margin: 0, paddingLeft: 18 }}>
                    {history.map((ev, i) => (
                      <li key={i} style={{ fontSize: 11, color: "var(--text2)", padding: "2px 0" }}>
                        {historyLine(ev)}
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
            {(doc.attention ?? []).length > 0 && (
              <div role="region" aria-label="Completeness"
                   style={{ border: "1px solid var(--red)", borderRadius: 6, padding: 8,
                            marginBottom: 8, background: "rgba(220,38,38,0.05)" }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--red)", marginBottom: 4 }}>
                  The page holds something this extraction does not
                </div>
                {(doc.attention ?? []).map(a => (
                  <div key={a.id} style={{ fontSize: 12, padding: "4px 0",
                                           borderTop: "1px solid var(--border)" }}>
                    <div style={{ color: "var(--text1)" }}>{a.text}</div>
                    {a.disposition ? (
                      <div style={{ fontSize: 11, color: "var(--text3)" }}>
                        {a.disposition.choice === "confirmed_absent"
                          ? "Confirmed absent" : "Entered by hand"}
                        {a.disposition.by ? ` — ${a.disposition.by}` : ""}
                      </div>
                    ) : (
                      <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                        <button className="btn btn-secondary btn-sm" disabled={busy}
                                onClick={() => settle(a, "confirmed_absent")}>
                          Confirmed absent
                        </button>
                        <button className="btn btn-secondary btn-sm" disabled={busy}
                                onClick={() => settle(a, "entered_manually")}>
                          I entered it by hand
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
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
                    <form onSubmit={e => { e.preventDefault(); submitEdit(v, editing); }}
                          onClick={e => e.stopPropagation()}
                          style={{ display: "flex", gap: 6, marginTop: 4 }}>
                      <input className="input" autoFocus value={editing}
                             aria-label={`${editMode === "correct" ? "Correct" : "Edit"} ${v.label}`}
                             onChange={e => setEditing(e.target.value)} style={{ flex: 1 }}/>
                      <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>
                        {editMode === "correct" ? "Save and accept" : "Save"}
                      </button>
                      <button className="btn btn-secondary btn-sm" type="button" disabled={busy}
                              onClick={() => setEditing(null)}>Cancel</button>
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
                      {editing === null && actionsFor(v).map(a => (
                        <button key={a.id} title={a.hint}
                                className={`btn btn-sm ${a.id === "accepted_as_is" ? "btn-primary" : "btn-secondary"}`}
                                disabled={busy}
                                onClick={e => {
                                  e.stopPropagation();
                                  if (a.id === "corrected") startEdit(v, "correct");
                                  else dispose(v, a.id);
                                }}>
                          {a.label} ({a.key})
                        </button>
                      ))}
                      {editing === null && v.resolved && (
                        <button className="btn btn-secondary btn-sm" disabled={busy}
                                onClick={e => { e.stopPropagation(); startEdit(v, "edit"); }}>
                          Edit (e)
                        </button>
                      )}
                      {v.disposition && (
                        <span style={{ fontSize: 10.5, color: "var(--text3)" }}>
                          {v.disposition === "accepted_as_is" ? "Accepted as is"
                            : v.disposition === "corrected" ? "Corrected" : "Confirmed empty"}
                        </span>
                      )}
                      <span style={{ fontSize: 10.5, color: "var(--text3)" }}>
                        {!v.page ? "No page recorded for this value, so no box."
                          : !meta ? ""
                          : b?.box_pt ? (b.ambiguous ? `Box: ${b.note ?? "one of several places it is printed"}.`
                                         : b.match === "line" ? "Box: the line it was read from" : "Box: the value")
                          : locationNotFound(b?.no_box_reason)}
                      </span>
                    </div>
                  )}
                </div>
              );
            })}
            {tables.length > 0 && !doc.failed && (
              <div role="region" aria-label="Add a missing row"
                   style={{ borderTop: "1px solid var(--border)", marginTop: 8, paddingTop: 8 }}>
                {addTable === null ? (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {tables.map(t => (
                      <button key={t.name} className="btn btn-secondary btn-sm" disabled={busy}
                              onClick={() => { setAddTable(t.name); setAddValues({}); }}>
                        Add row to {t.name}
                      </button>
                    ))}
                  </div>
                ) : (
                  <form onSubmit={e => { e.preventDefault(); addRow(); }}
                        style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text1)" }}>
                      New row in {addTable} — typed by you, marked as edited
                    </div>
                    {(tables.find(t => t.name === addTable)?.columns ?? []).map(c => (
                      <label key={c} style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
                        <span style={{ width: 120, color: "var(--text3)" }}>{c}</span>
                        <input className="input" style={{ flex: 1 }} aria-label={`New row ${c}`}
                               value={addValues[c] ?? ""}
                               onChange={e => setAddValues(s => ({ ...s, [c]: e.target.value }))}/>
                      </label>
                    ))}
                    {openAttention.length > 0 && (
                      <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
                        <span style={{ width: 120, color: "var(--text3)" }}>Answers</span>
                        <select className="input" style={{ flex: 1 }} value={addReason}
                                aria-label="Completeness reason this row answers"
                                onChange={e => setAddReason(e.target.value)}>
                          <option value="">no completeness reason</option>
                          {openAttention.map(a => <option key={a.id} value={a.id}>{a.text}</option>)}
                        </select>
                      </label>
                    )}
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn btn-primary btn-sm" type="submit" disabled={busy}>Add row</button>
                      <button className="btn btn-secondary btn-sm" type="button" disabled={busy}
                              onClick={() => setAddTable(null)}>Cancel</button>
                    </div>
                  </form>
                )}
              </div>
            )}
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
