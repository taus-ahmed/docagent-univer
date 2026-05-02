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
  const [SheetComp, setSheetComp] = useState<React.ComponentType<any> | null>(null);
  const sheetsRef = useRef<any[]>([]);
  const nameRef = useRef("");

  useEffect(() => { nameRef.current = name; }, [name]);
  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!mounted) return;
    import("@/components/templates/DocAgentSpreadsheet")
      .then(m => setSheetComp(() => m.default))
      .catch(console.error);
  }, [mounted]);

  const { data: existing } = useQuery<ColumnTemplate>({
    queryKey: ["template", templateId],
    queryFn: () => templatesApi.get(templateId!),
    enabled: !!templateId,
  });

  useEffect(() => {
    if (existing) {
      setName(existing.name);
      nameRef.current = existing.name;
      setDocType(existing.document_type);
    }
  }, [existing]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const n = nameRef.current.trim();
      if (!n) throw new Error("Enter a template name");
      const data = sheetsRef.current;
      let cols: TemplateColumn[] = [];
      if (data?.length) {
        const row0 = (data[0].celldata ?? [])
          .filter((c: any) => c.r === 0)
          .sort((a: any, b: any) => a.c - b.c);
        cols = row0
          .map((cell: any) => String(cell.v?.v ?? "").trim())
          .filter(Boolean)
          .map((nm: string, i: number) => ({ name: nm, type: "Text" as const, order: i }));
      }
      if (!cols.length) throw new Error("Type at least one column name in row 1");
      const payload = { name: n, document_type: docType, columns: cols };
      return templateId ? templatesApi.update(templateId, payload) : templatesApi.create(payload);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["templates"] }); toast.success("Template saved"); router.push("/templates"); },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!mounted) return null;

  return (
    <AppLayout>
      <div style={{ display:"flex", flexDirection:"column", height:"calc(100vh - 48px)", overflow:"hidden", margin:"-24px -28px 0", background:"#f3f4f6" }}>

        {/* TOP BAR - always visible, never scrolls */}
        <div style={{ flexShrink:0, background:"#fff", borderBottom:"1px solid #e5e7eb", padding:"0 24px", height:56, display:"flex", alignItems:"center", gap:12, boxShadow:"0 1px 3px rgba(0,0,0,0.06)" }}>
          <span style={{ fontSize:13, color:"#9ca3af", cursor:"pointer", whiteSpace:"nowrap" }} onClick={() => router.push("/templates")}>Templates</span>
          <span style={{ color:"#e5e7eb", fontSize:18 }}>&#8250;</span>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Untitled template"
            onKeyDown={e => e.stopPropagation()}
            onKeyUp={e => e.stopPropagation()}
            style={{ flex:1, fontSize:15, fontWeight:600, color:"#111", background:"transparent", border:"none", outline:"none", fontFamily:"inherit", minWidth:0 }}
          />
          <div style={{ display:"flex", alignItems:"center", gap:8, flexShrink:0 }}>
            <span style={{ fontSize:12, color:"#6b7280" }}>Type:</span>
            <select value={docType} onChange={e => setDocType(e.target.value)}
              style={{ padding:"5px 8px", border:"1px solid #e5e7eb", borderRadius:6, fontSize:12, background:"#f9fafb", outline:"none", cursor:"pointer", fontFamily:"inherit" }}>
              {DOC_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
            <button onClick={() => router.push("/templates")}
              style={{ padding:"6px 14px", borderRadius:7, border:"1px solid #e5e7eb", background:"#fff", fontSize:13, fontWeight:500, cursor:"pointer", color:"#6b7280", fontFamily:"inherit" }}>
              Cancel
            </button>
            <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}
              style={{ padding:"7px 18px", borderRadius:7, border:"none", background:"#4f46e5", fontSize:13, fontWeight:600, cursor:"pointer", color:"#fff", fontFamily:"inherit", display:"flex", alignItems:"center", gap:6, boxShadow:"0 1px 3px rgba(79,70,229,0.3)", opacity:saveMutation.isPending?0.7:1 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              {saveMutation.isPending ? "Saving..." : "Save template"}
            </button>
          </div>
        </div>

        {/* HINT BAR */}
        <div style={{ flexShrink:0, background:"#fffbeb", borderBottom:"1px solid #fde68a", padding:"7px 24px", fontSize:12, color:"#92400e", display:"flex", alignItems:"center", gap:6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Type column names in <strong style={{ margin:"0 2px" }}>Row 1</strong> (e.g. Invoice Number, Vendor, Total, SKU, Price). Use the toolbar to format cells.
        </div>

        {/* SHEET - fills remaining space, scrolls independently */}
        <div style={{ flex:1, minHeight:0, padding:16, overflow:"hidden" }}>
          <div style={{ height:"100%", border:"1px solid #e5e7eb", borderRadius:10, overflow:"hidden", boxShadow:"0 1px 6px rgba(0,0,0,0.05)", background:"#fff" }}>
            {SheetComp ? (
              <SheetComp
                initialColumns={existing?.columns ?? []}
                onSheetsChange={(data: any[]) => { sheetsRef.current = data; }}
                height="100%"
              />
            ) : (
              <div style={{ height:"100%", display:"flex", alignItems:"center", justifyContent:"center", background:"#f9fafb" }}>
                <div style={{ textAlign:"center" }}>
                  <div style={{ width:28, height:28, border:"3px solid #e5e7eb", borderTopColor:"#4f46e5", borderRadius:"50%", animation:"spin 0.7s linear infinite", margin:"0 auto 10px" }} />
                  <p style={{ fontSize:13, color:"#9ca3af" }}>Loading spreadsheet...</p>
                </div>
              </div>
            )}
          </div>
        </div>

      </div>
    </AppLayout>
  );
}