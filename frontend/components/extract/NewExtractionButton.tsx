"use client";

// Run Q, UI1: "New extraction" — extract a finished job's files again as a
// NEW job, with another template or none. The current job, its values and its
// download stay exactly as they are; the new job appears in History.

import { useState } from "react";
import toast from "react-hot-toast";
import { extractApi, type ColumnTemplate } from "@/lib/api";

interface Props {
  jobId: number;
  templates: ColumnTemplate[];
  /** called with the NEW job's id once it has started */
  onStarted?: (newJobId: number) => void;
}

export default function NewExtractionButton({ jobId, templates, onStarted }: Props) {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<string>("none");
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      const tid = choice === "none" ? null : Number(choice);
      const res = await extractApi.rerun(jobId, tid);
      toast.success(`New extraction started (job ${res.job_id}); job ${jobId} is unchanged`);
      setOpen(false);
      onStarted?.(res.job_id);
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Could not start a new extraction");
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button className="btn btn-secondary btn-sm" onClick={() => setOpen(true)}
              title="Extract these files again as a new job; this job stays as it is">
        New extraction
      </button>
    );
  }
  return (
    <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
      <select className="input" aria-label="Template for the new extraction"
              value={choice} onChange={e => setChoice(e.target.value)}
              style={{ fontSize: 12, padding: "4px 6px" }}>
        <option value="none">No template</option>
        {templates.map(t => <option key={t.id} value={String(t.id)}>{t.name}</option>)}
      </select>
      <button className="btn btn-primary btn-sm" onClick={run} disabled={busy}>
        {busy ? "Starting…" : "Run as new job"}
      </button>
      <button className="btn btn-secondary btn-sm" onClick={() => setOpen(false)} disabled={busy}>
        Cancel
      </button>
    </span>
  );
}
