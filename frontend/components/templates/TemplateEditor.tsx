"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { templatesApi, type TemplateColumn, type ColumnTemplate } from "@/lib/api";
import toast from "react-hot-toast";
import dynamic from "next/dynamic";

const FortuneSheetEditor = dynamic(
  () => import("@/components/templates/FortuneSheetInner"),
  {
    ssr: false,
    loading: () => (
      <div style={{ height: 480, display: "flex", alignItems: "center", justifyContent: "center", background: "#f8f9fb", border: "1px solid #e3e6ec", borderRadius: 10 }}>
        <p style={{ fontSize: 13, color: "#9ca3af" }}>Loading spreadsheet…</p>
      </div>
    )
  }
);

const DOC_TYPES = ["invoice","receipt","purchase_order","bank_statement","contract","other"];

interface Props { templateId?: number }

export default function TemplateEditor({ templateId }: Props) {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [docType, setDocType] = useState("invoice");
  const [mounted, setMounted] = useState(false);
  const sheetsDataRef = useRef<any[]>([]);
  const initialColsRef = useRef<TemplateColumn[]>([]);

  useEffect(() => { setMounted(true); }, []);

  const { data: existing } = useQuery<ColumnTemplate>({
    queryKey: ["template", templateId],
    queryFn: () => templatesApi.get(templateId!),
    enabled: !!templateId,
  });

  useEffect(() => {
    if (existing) {
      setName(existing.name);
      setDocType(existing.document_type);
      initialColsRef.current = existing.columns;
    }
  }, [existing]);

  function extractColumnsFromSheets(data: any[]): TemplateColumn[] {
    if (!data?.length) return [];
    const sheet = data[0];
    const celldata: any[] = sheet.celldata ?? sheet.data ?? [];
    
    // Get all cells in row 0
    const row0 = celldata
      .filter((c: any) => c.r === 0)
      .sort((a: any, b: any) => a.c - b.c);

    const cols: TemplateColumn[] = [];
    for (const cell of row0) {
      const val = String(cell.v?.v ?? cell.v?.m ?? cell.v ?? "").trim();
      if (val && val !== "undefined") {
        cols.push({ name: val, type: "Text", order: cell.c });
      }
    }
    return cols;
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error("Enter a template name");
      
      const cols = extractColumnsFromSheets(sheetsDataRef.current);
      if (!cols.length) throw new Error("Type at least one column name in row 1 of the sheet");

      const payload = {
        name: name.trim(),
        document_type: docType,
        columns: cols,
      };

      if (templateId) return templatesApi.update(templateId, payload);
      return templatesApi.create(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      toast.success("Template saved!");
      router.push("/templates");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!mounted) return null;

  return (
    <AppLayout>
      <div style={{ display:"flex", flexDirection:"column", height:"calc(100vh - 48px)", overflow:"hidden" }}>
        {/* Header */}
        <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:12, gap:12, flexWrap:"wrap", flexShrink:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            <span style={{ fontSize:12, color:"var(--text3)", cursor:"pointer" }} onClick={() => router.push("/templates")}>
              Templates
            </span>
            <span style={{ color:"var(--border2)" }}>›</span>
            <input
              style={{ fontSize:16, fontWeight:600, color:"var(--text1)", background:"transparent", border:"none", borderBottom:"1.5px solid transparent", outline:"none", padding:"2px 4px", letterSpacing:"-0.02em", transition:"border-color 0.15s", minWidth:200 }}
              onFocus={e => e.currentTarget.style.borderBottomColor="var(--accent)"}
              onBlur={e => e.currentTarget.style.borderBottomColor="transparent"}
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Template name…"
              autoFocus={!templateId}
            />
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:8 }}>
            <div style={{ display:"flex", alignItems:"center", gap:6, fontSize:12, color:"var(--text2)" }}>
              Doc type:
              <select className="input" style={{ width:"auto", padding:"4px 10px" }} value={docType} onChange={e => setDocType(e.target.value)}>
                {DOC_TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => router.push("/templates")}>Cancel</button>
            <button className="btn btn-primary btn-sm" onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
              {saveMutation.isPending ? "Saving…" : "💾 Save template"}
            </button>
          </div>
        </div>

        {/* Instructions */}
        <div style={{ background:"#fffbeb", border:"1px solid #fde68a", borderRadius:8, padding:"8px 14px", marginBottom:10, fontSize:12, color:"#92400e", flexShrink:0 }}>
          💡 Type column headers in <b>Row 1</b> (e.g. Invoice Number, Vendor Name, Total, SKU, Price). Rows 2+ are for sample data. Click <b>Save template</b> when done.
        </div>

        {/* Sheet - takes remaining height, no overflow */}
        <div style={{ flex:1, minHeight:0, overflow:"hidden" }}>
          <FortuneSheetEditor
            initialColumns={initialColsRef.current}
            onSheetsChange={(data: any[]) => { sheetsDataRef.current = data; }}
            height="100%"
          />
        </div>
      </div>
    </AppLayout>
  );
}