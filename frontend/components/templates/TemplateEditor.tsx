"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { templatesApi, type TemplateColumn, type ColumnTemplate } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import toast from "react-hot-toast";
import Link from "next/link";

const DOC_TYPES = ["invoice","receipt","purchase_order","bank_statement","contract","other"];
interface Props { templateId?: number }

export default function TemplateEditor({ templateId }: Props) {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, isAuthenticated, logout } = useAuthStore();
  const [name, setName] = useState("");
  const [docType, setDocType] = useState("invoice");
  const [mounted, setMounted] = useState(false);
  const [SheetComp, setSheetComp] = useState<React.ComponentType<any> | null>(null);
  const sheetsRef = useRef<any[]>([]);
  const nameRef = useRef("");

  useEffect(() => { nameRef.current = name; }, [name]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    if (!isAuthenticated) { router.replace("/login"); return; }
    import("@/components/templates/DocAgentSpreadsheet")
      .then(m => setSheetComp(() => m.default))
      .catch(console.error);
  }, [mounted, isAuthenticated]);

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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      toast.success("Template saved");
      router.push("/templates");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!mounted || !isAuthenticated) return null;

  const initials = user?.display_name?.split(" ").map((w: string) => w[0]).slice(0,2).join("").toUpperCase() ?? "U";

  return (
    <div style={{ display:"flex", height:"100vh", overflow:"hidden", background:"#f3f4f6", fontFamily:"'Segoe UI',system-ui,sans-serif" }}>

      {/* ── SIDEBAR ── */}
      <aside style={{ width:220, background:"#1e2130", display:"flex", flexDirection:"column", flexShrink:0 }}>
        <div style={{ padding:"16px 16px 14px", borderBottom:"1px solid rgba(255,255,255,0.06)", display:"flex", alignItems:"center", gap:10 }}>
          <div style={{ width:32, height:32, background:"#4f46e5", borderRadius:8, display:"grid", placeItems:"center", fontSize:15, fontWeight:700, color:"#fff", flexShrink:0 }}>D</div>
          <span style={{ fontSize:15, fontWeight:700, color:"#e2e5f0" }}>DocAgent</span>
        </div>
        <nav style={{ padding:"10px 8px", flex:1 }}>
          {[{href:"/extract",label:"Extract"},{href:"/history",label:"History"},{href:"/templates",label:"Templates",active:true}].map(item => (
            <Link key={item.href} href={item.href} style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 10px", borderRadius:6, fontSize:13, color: item.active ? "#818cf8" : "#8b90ae", background: item.active ? "rgba(79,70,229,0.2)" : "transparent", marginBottom:2, textDecoration:"none", fontWeight: item.active ? 500 : 400 }}>
              {item.label}
            </Link>
          ))}
          {user?.role === "admin" && (
            <>
              <div style={{ fontSize:10, fontWeight:700, textTransform:"uppercase", letterSpacing:"0.08em", color:"#555a7a", padding:"8px 10px 4px", marginTop:8 }}>Admin</div>
              {[{href:"/analytics",label:"Analytics"},{href:"/admin",label:"Admin"}].map(item => (
                <Link key={item.href} href={item.href} style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 10px", borderRadius:6, fontSize:13, color:"#8b90ae", marginBottom:2, textDecoration:"none" }}>
                  {item.label}
                </Link>
              ))}
            </>
          )}
        </nav>
        <div style={{ padding:"12px 14px", borderTop:"1px solid rgba(255,255,255,0.06)", display:"flex", alignItems:"center", gap:8 }}>
          <div style={{ width:28, height:28, background:"rgba(99,102,241,0.3)", borderRadius:"50%", display:"grid", placeItems:"center", fontSize:11, color:"#818cf8", fontWeight:600, flexShrink:0 }}>{initials}</div>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ fontSize:12, fontWeight:600, color:"#e2e5f0", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{user?.display_name}</div>
            <div style={{ fontSize:10, color:"#8b90ae" }}>{user?.role}</div>
          </div>
          <button onClick={() => { logout(); router.replace("/login"); }} style={{ background:"transparent", border:"none", color:"#8b90ae", cursor:"pointer", fontSize:11, padding:4 }}>Out</button>
        </div>
      </aside>

      {/* ── MAIN ── */}
      <div style={{ flex:1, display:"flex", flexDirection:"column", overflow:"hidden", minWidth:0 }}>

        {/* TOP BAR */}
        <div style={{ flexShrink:0, background:"#fff", borderBottom:"1px solid #e5e7eb", height:56, display:"flex", alignItems:"center", padding:"0 24px", gap:12, boxShadow:"0 1px 3px rgba(0,0,0,0.05)" }}>
          <span onClick={() => router.push("/templates")} style={{ fontSize:13, color:"#9ca3af", cursor:"pointer", whiteSpace:"nowrap", flexShrink:0 }}>Templates</span>
          <span style={{ color:"#d1d5db", flexShrink:0 }}>&#8250;</span>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Untitled template"
            onKeyDown={e => e.stopPropagation()}
            onKeyUp={e => e.stopPropagation()}
            style={{ flex:1, minWidth:0, fontSize:15, fontWeight:600, color:"#111", background:"transparent", border:"none", outline:"none", fontFamily:"inherit" }}
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
              style={{ padding:"7px 18px", borderRadius:7, border:"none", background:"#4f46e5", fontSize:13, fontWeight:600, cursor: saveMutation.isPending ? "not-allowed" : "pointer", color:"#fff", fontFamily:"inherit", display:"flex", alignItems:"center", gap:6, boxShadow:"0 1px 3px rgba(79,70,229,0.3)", opacity: saveMutation.isPending ? 0.7 : 1 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              {saveMutation.isPending ? "Saving..." : "Save template"}
            </button>
          </div>
        </div>

        {/* HINT BAR */}
        <div style={{ flexShrink:0, background:"#fffbeb", borderBottom:"1px solid #fde68a", padding:"7px 24px", fontSize:12, color:"#92400e", display:"flex", alignItems:"center", gap:6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Type column names in <strong style={{ margin:"0 3px" }}>Row 1</strong> (e.g. Invoice Number, Vendor, Total, SKU, Price). Rows 2+ are sample data.
        </div>

        {/* SHEET — only this area scrolls */}
        <div style={{ flex:1, minHeight:0, padding:16, overflow:"hidden", display:"flex", flexDirection:"column" }}>
          <div style={{ flex:1, minHeight:0, border:"1px solid #e5e7eb", borderRadius:10, overflow:"hidden", boxShadow:"0 1px 6px rgba(0,0,0,0.05)", background:"#fff" }}>
            {SheetComp ? (
              <SheetComp
                initialColumns={existing?.columns ?? []}
                onSheetsChange={(data: any[]) => { sheetsRef.current = data; }}
                height="100%"
              />
            ) : (
              <div style={{ height:"100%", display:"flex", alignItems:"center", justifyContent:"center", background:"#f9fafb" }}>
                <p style={{ fontSize:13, color:"#9ca3af" }}>Loading spreadsheet...</p>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}