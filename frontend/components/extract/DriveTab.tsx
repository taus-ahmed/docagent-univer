"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { driveApi, type ColumnTemplate, type DriveFolderContents } from "@/lib/api";
import toast from "react-hot-toast";

interface Props {
  selectedTemplate: ColumnTemplate | null;
  clientId: string;
  onJobStarted: (jobId: number) => void;
}

export default function DriveTab({ selectedTemplate, clientId, onJobStarted }: Props) {
  const qc = useQueryClient();
  const [browseFolderId, setBrowseFolderId] = useState("root");
  const [breadcrumb, setBreadcrumb] = useState<{ id: string; name: string }[]>([]);
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [selectedFolderName, setSelectedFolderName] = useState<string>("");

  const { data: authStatus } = useQuery({
    queryKey: ["drive-auth"],
    queryFn: driveApi.authStatus,
  });

  const { data: folderContents, isLoading: browseLoading } = useQuery<DriveFolderContents>({
    queryKey: ["drive-folder", browseFolderId],
    queryFn: () => driveApi.listFolder(browseFolderId),
    enabled: authStatus?.is_authenticated === true,
  });

  const { data: watchFolders = [] } = useQuery({
    queryKey: ["watch-folders"],
    queryFn: driveApi.listWatchFolders,
    enabled: authStatus?.is_authenticated === true,
  });

  const authMutation = useMutation({
    mutationFn: driveApi.authenticate,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["drive-auth"] });
      toast.success("Drive connected");
    },
    onError: () => toast.error("Authentication failed"),
  });

  const extractMutation = useMutation({
    mutationFn: () => driveApi.extractFolder(selectedFolderId!, clientId, selectedTemplate?.id),
    onSuccess: (data: any) => {
      onJobStarted(data.job_id);
      toast.success(`Drive extraction started`);
    },
    onError: () => toast.error("Drive extraction failed"),
  });

  const addWatchMutation = useMutation({
    mutationFn: () => driveApi.addWatchFolder({
      folder_id: selectedFolderId!,
      folder_name: selectedFolderName,
      client_id: clientId,
      auto_upload_results: true,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["watch-folders"] });
      toast.success(`Watching "${selectedFolderName}"`);
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail ?? "Failed to add watch folder"),
  });

  function navigateInto(id: string, name: string) {
    setBreadcrumb(prev => [...prev, { id: browseFolderId, name: browseFolderId === "root" ? "My Drive" : name }]);
    setBrowseFolderId(id);
  }

  function navigateBack(idx: number) {
    const crumb = breadcrumb[idx];
    setBreadcrumb(prev => prev.slice(0, idx));
    setBrowseFolderId(crumb.id);
  }

  if (!authStatus?.is_configured) {
    return (
      <div style={{ padding: "14px 0", textAlign: "center" }}>
        <p style={{ fontSize: 12, color: "var(--text3)", marginBottom: 10 }}>Google Drive not configured</p>
        <p style={{ fontSize: 11, color: "var(--text4)" }}>Add credentials.json to the backend folder</p>
      </div>
    );
  }

  if (!authStatus?.is_authenticated) {
    return (
      <div style={{ padding: "10px 0" }}>
        <button
          className="btn btn-primary btn-full"
          onClick={() => authMutation.mutate()}
          disabled={authMutation.isPending}
        >
          {authMutation.isPending ? (
            <><svg className="animate-spin" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Connecting…</>
          ) : (
            <><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg> Connect Google Drive</>
          )}
        </button>
        <p style={{ fontSize: 11, color: "var(--text4)", marginTop: 8, textAlign: "center" }}>
          OAuth browser window will open
        </p>
      </div>
    );
  }

  return (
    <div>
      <style>{`
        .drive-status { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; font-size: 12px; color: var(--green); }
        .drive-breadcrumb { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; }
        .bc-item { font-size: 11px; color: var(--text3); cursor: pointer; }
        .bc-item:hover { color: var(--text1); }
        .bc-sep { color: var(--text4); font-size: 11px; }
        .drive-list { max-height: 180px; overflow-y: auto; margin-bottom: 10px; }
        .drive-item {
          display: flex; align-items: center; gap: 8px;
          padding: 6px 8px; border-radius: 6px; cursor: pointer;
          font-size: 12px; color: var(--text2);
          transition: background 0.1s;
        }
        .drive-item:hover { background: var(--surface2); color: var(--text1); }
        .drive-item.selected { background: var(--accent-dim); color: var(--accent); border: 1px solid var(--accent-border); }
        .drive-count { font-size: 10px; color: var(--text3); margin-left: auto; }
        .watch-section { margin-top: 12px; }
        .watch-list { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
        .watch-item {
          display: flex; align-items: center; gap: 7px;
          padding: 6px 8px; background: var(--surface2);
          border: 1px solid var(--border); border-radius: 6px; font-size: 11px;
        }
        .watch-name { flex: 1; color: var(--text2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .watch-last { color: var(--text4); font-size: 10px; }
      `}</style>

      <div className="drive-status">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="var(--green)"><circle cx="12" cy="12" r="10"/></svg>
        Drive connected
      </div>

      {/* Breadcrumb */}
      <div className="drive-breadcrumb">
        <span className="bc-item" onClick={() => { setBreadcrumb([]); setBrowseFolderId("root"); }}>My Drive</span>
        {breadcrumb.map((crumb, i) => (
          <span key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span className="bc-sep">›</span>
            <span className="bc-item" onClick={() => navigateBack(i)}>{crumb.name}</span>
          </span>
        ))}
      </div>

      {/* Folder list */}
      <div className="drive-list">
        {browseLoading ? (
          <p style={{ fontSize: 12, color: "var(--text3)", textAlign: "center", padding: "12px 0" }}>Loading…</p>
        ) : (
          <>
            {folderContents?.folders.map(f => (
              <div
                key={f.id}
                className={`drive-item ${selectedFolderId === f.id ? "selected" : ""}`}
                onClick={() => { setSelectedFolderId(f.id); setSelectedFolderName(f.name); }}
                onDoubleClick={() => navigateInto(f.id, f.name)}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                {f.name}
                <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text4)" }}>double-click to open</span>
              </div>
            ))}
            {folderContents?.folders.length === 0 && (
              <p style={{ fontSize: 11, color: "var(--text4)", textAlign: "center", padding: "8px 0" }}>No subfolders</p>
            )}
          </>
        )}
      </div>

      {selectedFolderId && (
        <div style={{ background: "var(--accent-dim)", border: "1px solid var(--accent-border)", borderRadius: 6, padding: "7px 10px", fontSize: 12, color: "var(--accent)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
          {selectedFolderName}
          <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--text3)" }}>
            {folderContents?.supported_files ?? 0} supported files
          </span>
        </div>
      )}

      <div style={{ display: "flex", gap: 6 }}>
        <button
          className="btn btn-primary btn-sm"
          style={{ flex: 1 }}
          disabled={!selectedFolderId || !selectedTemplate || extractMutation.isPending}
          onClick={() => extractMutation.mutate()}
        >
          {extractMutation.isPending ? "Extracting…" : "Extract folder"}
        </button>
        <button
          className="btn btn-secondary btn-sm"
          disabled={!selectedFolderId || addWatchMutation.isPending}
          onClick={() => addWatchMutation.mutate()}
          title="Auto-process new files added to this folder"
        >
          {addWatchMutation.isPending ? "…" : "Watch"}
        </button>
      </div>

      {/* Watch folders */}
      {watchFolders.length > 0 && (
        <div className="watch-section">
          <div className="label" style={{ marginBottom: 6 }}>Watched folders</div>
          <div className="watch-list">
            {watchFolders.map(wf => (
              <div key={wf.id} className="watch-item">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="var(--amber)" strokeWidth="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                <span className="watch-name">{wf.folder_name}</span>
                <span className="watch-last">
                  {wf.last_checked ? new Date(wf.last_checked).toLocaleDateString() : "never"}
                </span>
                <button onClick={() => driveApi.removeWatchFolder(wf.id).then(() => qc.invalidateQueries({ queryKey: ["watch-folders"] }))} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text4)", padding: 0 }}>
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
