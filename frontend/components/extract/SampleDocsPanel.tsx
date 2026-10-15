"use client";

/**
 * "Sample documents" — the PDFs shipped with a demo tenant.
 *
 * Rendered only for a demo account, and even then this component is not the
 * control: the backend serves `/api/demo/*` as 404 to everyone else, so hiding
 * the panel is a courtesy to the normal user, not the enforcement. The normal
 * Upload dropzone is untouched and stays available next to it.
 *
 * Starting an extraction is the PAGE's job, not this panel's — `onUse` hands
 * the filename back up so a sample run goes through exactly the same job
 * bookkeeping (and the same polling) as a user's own upload.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import toast from "react-hot-toast";
import { demoApi, type SampleDoc } from "@/lib/api";

function sizeLabel(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function SampleDocsPanel({
  enabled,
  busy,
  onUse,
}: {
  enabled: boolean;
  busy: boolean;
  onUse: (filename: string) => void | Promise<void>;
}) {
  const [downloading, setDownloading] = useState<string | null>(null);

  const { data: docs = [], isLoading } = useQuery<SampleDoc[]>({
    queryKey: ["demo-sample-docs"],
    queryFn: demoApi.listSampleDocs,
    enabled,
    staleTime: 5 * 60 * 1000,
  });

  if (!enabled) return null;
  if (!isLoading && docs.length === 0) return null;

  async function download(filename: string) {
    setDownloading(filename);
    try {
      const blob = await demoApi.downloadSampleDoc(filename);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast.error("Could not download that sample");
    } finally {
      setDownloading(null);
    }
  }

  return (
    <div className="card" style={{ padding: 14 }}>
      <span className="label" style={{ display: "block", marginBottom: 4 }}>
        Sample documents
      </span>
      <p style={{ fontSize: 11, color: "var(--text4)", marginBottom: 10 }}>
        Ready-made PDFs for this demo — extract one, or download it to upload yourself.
      </p>

      {isLoading ? (
        <p style={{ fontSize: 12, color: "var(--text3)" }}>Loading…</p>
      ) : (
        docs.map(doc => (
          <div key={doc.filename} className="file-item">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--accent)"
                 strokeWidth="2" aria-hidden="true">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <span className="file-name">{doc.filename}</span>
            <span className="file-size">{sizeLabel(doc.size_bytes)}</span>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => download(doc.filename)}
              disabled={downloading === doc.filename}
              style={{ fontSize: 11, padding: "2px 8px" }}
            >
              {downloading === doc.filename ? "…" : "Download"}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => onUse(doc.filename)}
              disabled={busy}
              style={{ fontSize: 11, padding: "2px 8px" }}
            >
              Extract
            </button>
          </div>
        ))
      )}
    </div>
  );
}
