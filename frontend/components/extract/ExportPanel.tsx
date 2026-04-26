"use client";

import { useState } from "react";
import { exportApi, type DocumentResult } from "@/lib/api";
import toast from "react-hot-toast";
import { Download, FileSpreadsheet, Loader2 } from "lucide-react";

interface Props {
  jobId: number;
  results: DocumentResult[];
}

export default function ExportPanel({ jobId, results }: Props) {
  const [loading, setLoading] = useState<"combined" | "perfile" | null>(null);

  async function exportCombined() {
    setLoading("combined");
    try {
      const blob = await exportApi.combined({ job_id: jobId, include_line_items: true });
      exportApi.downloadBlob(blob, `docagent_job${jobId}_combined.xlsx`);
      toast.success("Downloaded combined Excel");
    } catch {
      toast.error("Export failed");
    } finally {
      setLoading(null);
    }
  }

  async function exportPerFile() {
    setLoading("perfile");
    try {
      const blob = await exportApi.perFile({ job_id: jobId });
      exportApi.downloadBlob(blob, `docagent_job${jobId}_perfile.xlsx`);
      toast.success("Downloaded per-file Excel");
    } catch {
      toast.error("Export failed");
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="card" style={{ padding: 16 }}>
      <p style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>
        Export
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <button className="btn-primary" onClick={exportCombined} disabled={!!loading} style={{ justifyContent: "center" }}>
          {loading === "combined"
            ? <><Loader2 size={14} className="animate-spin" /> Generating…</>
            : <><FileSpreadsheet size={14} /> Combined Excel</>
          }
        </button>
        <button className="btn-secondary" onClick={exportPerFile} disabled={!!loading} style={{ justifyContent: "center" }}>
          {loading === "perfile"
            ? <><Loader2 size={14} className="animate-spin" /> Generating…</>
            : <><Download size={14} /> Per-file Excel</>
          }
        </button>
      </div>
      <p style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 8 }}>
        {results.length} document{results.length !== 1 ? "s" : ""} · all fields included
      </p>
    </div>
  );
}
