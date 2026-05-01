"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import AppLayout from "@/components/layout/AppLayout";
import { templatesApi, type TemplateColumn, type ColumnTemplate } from "@/lib/api";
import toast from "react-hot-toast";

const DOC_TYPES = ["invoice","receipt","purchase_order","bank_statement","contract","other"];

interface Props { templateId?: number }

export default function TemplateEditor({ templateId }: Props) {
  const router = useRouter();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [docType, setDocType] = useState("invoice");
  const [mounted, setMounted] = useState(false);
  const [SheetEditor, setSheetEditor] = useState<React.ComponentType<any> | null>(null);
  const columnsRef = useRef<TemplateColumn[]>([]);

  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!mounted) return;
    import("@/components/templates/FortuneSheetEditor")
      .then(m => setSheetEditor(() => m.default))
      .catch(err => console.error("Sheet load failed:", err));
  }, [mounted]);

  const { data: existing } = useQuery<ColumnTemplate>({
    queryKey: ["template", templateId],
    queryFn: () => templatesApi.get(templateId!),
    enabled: !!templateId,
  });

  useEffect(() => {
    if (existing) {
      setName(existing.name);
      setDocType(existing.document_type);
      columnsRef.current = existing.columns;
    }
  }, [existing]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw new Error("Enter a template name");
      
      // Get columns directly from the sheet via ref
      const cols = columnsRef.current.filter(c => c.name.trim());
      if (!cols.length) throw new Error("Type at least one column name in row 1 of the sheet");

      const payload = {
        name: name.trim(),
        document_type: docType,
        columns: cols.map((c, i) => ({ name: c.name.trim(), type: "Text" as const, order: i })),
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
      {/* Header */}
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:16, gap:12, flexWrap:"wrap" }}>
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
      <div style={{ background:"#fffbeb", border:"1px solid #fde68a", borderRadius:8, padding:"10px 14px", marginBottom:14, fontSize:12, color:"#92400e" }}>
        💡 <b>How to create a template:</b> Type your column headers in <b>Row 1</b> (e.g. Invoice Number, Vendor Name, Total, SKU, Price). 
        Rows 2+ are for sample data. When done, enter a name above and click <b>Save template</b>.
      </div>

      {/* Sheet */}
      {SheetEditor ? (
        <SheetEditor
          initialColumns={columnsRef.current}
          onColumnsChange={(cols: TemplateColumn[]) => { columnsRef.current = cols; }}
          height={520}
        />
      ) : (
        <div style={{ height:520, display:"flex", alignItems:"center", justifyContent:"center", background:"var(--surface2)", border:"1px solid var(--border)", borderRadius:"var(--radius-lg)" }}>
          <div style={{ textAlign:"center" }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" style={{ margin:"0 auto 10px", display:"block", animation:"spin 0.8s linear infinite" }}>
              <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
            </svg>
            <p style={{ fontSize:13, color:"var(--text3)" }}>Loading spreadsheet…</p>
          </div>
        </div>
      )}
    </AppLayout>
  );
}