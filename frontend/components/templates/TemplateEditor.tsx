"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { templatesApi, type TemplateColumn, type ColumnTemplate } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";
import toast from "react-hot-toast";
import Link from "next/link";
import type { SheetSaveData } from "@/components/templates/DocAgentSpreadsheet";

const DOC_TYPES = [
  { value: "invoice",        label: "Invoice" },
  { value: "receipt",        label: "Receipt" },
  { value: "purchase_order", label: "Purchase Order" },
  { value: "bank_statement", label: "Bank Statement" },
  { value: "contract",       label: "Contract" },
  { value: "other",          label: "Other..." },
];

interface Props { templateId?: number }

export default function TemplateEditor({ templateId }: Props) {
  const router = useRouter();
  const qc = useQueryClient();
  const { user, isAuthenticated, logout } = useAuthStore();
  const [name, setName] = useState("");
  const [docType, setDocType] = useState("invoice");
  const [customDocType, setCustomDocType] = useState("");
  const [mounted, setMounted] = useState(false);
  const [SheetComp, setSheetComp] = useState<React.ComponentType<any> | null>(null);
  const sheetDataRef = useRef<SheetSaveData | null>(null);
  const nameRef = useRef("");

  useEffect(() => { nameRef.current = name; }, [name]);
  useEffect(() => { setMounted(true); }, []);

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
    if (!existing) return;
    setName(existing.name);
    nameRef.current = existing.name;
    const isStandard = DOC_TYPES.some(t => t.value === existing.document_type && t.value !== "other");
    if (isStandard) { setDocType(existing.document_type); }
    else { setDocType("other"); setCustomDocType(existing.document_type); }
  }, [existing]);

  // Parse existing template's saved layout
  const existingLayout = (() => {
    if (!existing?.columns) return null;
    try {
      // Description holds the full grid JSON
      const desc = (existing as any).description;
      if (desc) return JSON.parse(desc) as SheetSaveData;
    } catch {}
    return null;
  })();

  const saveMutation = useMutation({
    mutationFn: async () => {
      const n = nameRef.current.trim();
      if (!n) throw new Error("Enter a template name");

      const finalDocType = docType === "other"
        ? (customDocType.trim() || "other")
        : docType;

      const sheetData = sheetDataRef.current;
      if (!sheetData) throw new Error("Spreadsheet not loaded yet — please wait");

      // Check if there are any cells with content
      const hasCells = Object.values(sheetData.cells ?? {}).some(c => c?.value?.trim());
      if (!hasCells) throw new Error("Add some content to the spreadsheet before saving");

      // Build columns list from extract targets OR all cells with values in row 0
      let cols: TemplateColumn[] = [];

      if (sheetData.extractTargets?.length > 0) {
        // Use explicitly marked extract targets
        cols = sheetData.extractTargets.map((t, i) => ({
          name: t.label,
          type: "Text" as const,
          order: i,
          extraction_type: t.isRepeat ? "lineitem" : "header",
        }));
      } else {
        // Auto-detect: use all cells that have values as columns
        // This handles the case where user forgets to mark Extract here
        const cellEntries = Object.entries(sheetData.cells ?? {});
        const allNamedCells = cellEntries
          .filter(([, cell]) => cell?.value?.trim())
          .map(([key, cell]) => {
            const [r, c] = key.split(",").map(Number);
            return { r, c, value: cell.value.trim() };
          })
          .sort((a, b) => a.r - b.r || a.c - b.c);

        cols = allNamedCells.map((cell, i) => ({
          name: cell.value,
          type: "Text" as const,
          order: i,
          extraction_type: "header" as const,
        }));
      }

      if (!cols.length) throw new Error("Add column names or mark cells for extraction");

      // Save full grid layout in description field for perfect restore
      const fullLayout = {
        ...sheetData,
        docType: finalDocType,
        savedAt: new Date().toISOString(),
      };

      const payload = {
        name: n,
        document_type: finalDocType,
        columns: cols,
        description: JSON.stringify(fullLayout),
      };

      return templateId
        ? templatesApi.update(templateId, payload as any)
        : templatesApi.create(payload as any);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["templates"] });
      toast.success("Template saved successfully");
      router.push("/templates");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (!mounted || !isAuthenticated) return null;

  const initials = user?.display_name?.split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase() ?? "U";

  return (
    <div style={{ display:"flex", height:"100vh", overflow:"hidden", background:"#f3f4f6", fontFamily:"'Segoe UI',system-ui,sans-serif" }}>
      {/* SIDEBAR */}
      <aside style={{ width:220, background:"#1e2130", display:"flex", flexDirection:"column", flexShrink:0 }}>
        <div style={{ padding:"16px", borderBottom:"1px solid rgba(255,255,255,0.06)", display:"flex", alignItems:"center", gap:10 }}>
          <div style={{ width:32, height:32, background:"#4f46e5", borderRadius:8, display:"grid", placeItems:"center", fontSize:15, fontWeight:700, color:"#fff", flexShrink:0 }}>D</div>
          <span style={{ fontSize:15, fontWeight:700, color:"#e2e5f0" }}>DocAgent</span>
        </div>
        <nav style={{ padding:"10px 8px", flex:1 }}>
          <div style={{ fontSize:10, fontWeight:700, textTransform:"uppercase" as const, letterSpacing:"0.08em", color:"#555a7a", padding:"4px 10px 8px" }}>Workspace</div>
          {[{href:"/extract",label:"Extract"},{href:"/history",label:"History"},{href:"/templates",label:"Templates",active:true}].map(item => (
            <Link key={item.href} href={item.href} style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 10px", borderRadius:6, fontSize:13, color:(item as any).active?"#818cf8":"#8b90ae", background:(item as any).active?"rgba(79,70,229,0.2)":"transparent", marginBottom:2, textDecoration:"none", fontWeight:(item as any).active?500:400 }}>
              {item.label}
            </Link>
          ))}
          {user?.role === "admin" && (
            <>
              <div style={{ fontSize:10, fontWeight:700, textTransform:"uppercase" as const, letterSpacing:"0.08em", color:"#555a7a", padding:"12px 10px 8px" }}>Admin</div>
              {[{href:"/analytics",label:"Analytics"},{href:"/admin",label:"Admin"}].map(item => (
                <Link key={item.href} href={item.href} style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 10px", borderRadius:6, fontSize:13, color:"#8b90ae", marginBottom:2, textDecoration:"none" }}>{item.label}</Link>
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

      {/* MAIN */}
      <div style={{ flex:1, display:"flex", flexDirection:"column", overflow:"hidden", minWidth:0 }}>
        {/* TOP BAR */}
        <div style={{ flexShrink:0, background:"#fff", borderBottom:"1px solid #e5e7eb", height:56, display:"flex", alignItems:"center", padding:"0 20px", gap:10, boxShadow:"0 1px 3px rgba(0,0,0,0.05)" }}>
          <span onClick={() => router.push("/templates")} style={{ fontSize:13, color:"#9ca3af", cursor:"pointer", whiteSpace:"nowrap", flexShrink:0 }}>Templates</span>
          <span style={{ color:"#d1d5db", flexShrink:0 }}>›</span>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Untitled template"
            onKeyDown={e => e.stopPropagation()} onKeyUp={e => e.stopPropagation()}
            style={{ flex:1, minWidth:0, fontSize:15, fontWeight:600, color:"#111", background:"transparent", border:"none", outline:"none", fontFamily:"inherit" }}
          />
          <div style={{ display:"flex", alignItems:"center", gap:8, flexShrink:0 }}>
            <span style={{ fontSize:12, color:"#6b7280", whiteSpace:"nowrap" }}>Document type:</span>
            <select value={docType} onChange={e => { setDocType(e.target.value); if (e.target.value !== "other") setCustomDocType(""); }}
              style={{ padding:"5px 8px", border:"1px solid #e5e7eb", borderRadius:6, fontSize:12, background:"#f9fafb", color:"#374151", outline:"none", cursor:"pointer", fontFamily:"inherit" }}>
              {DOC_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            {docType === "other" && (
              <input value={customDocType} onChange={e => setCustomDocType(e.target.value)} placeholder="e.g. Medical Invoice"
                onKeyDown={e => e.stopPropagation()} onKeyUp={e => e.stopPropagation()}
                style={{ padding:"5px 10px", border:"1px solid #a5b4fc", borderRadius:6, fontSize:12, background:"#f0f0ff", color:"#374151", outline:"none", fontFamily:"inherit", width:150 }}
              />
            )}
            <button onClick={() => router.push("/templates")} style={{ padding:"6px 14px", borderRadius:7, border:"1px solid #e5e7eb", background:"#fff", fontSize:13, fontWeight:500, cursor:"pointer", color:"#6b7280", fontFamily:"inherit" }}>Cancel</button>
            <button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}
              style={{ padding:"7px 18px", borderRadius:7, border:"none", background:"#4f46e5", fontSize:13, fontWeight:600, cursor:saveMutation.isPending?"not-allowed":"pointer", color:"#fff", fontFamily:"inherit", display:"flex", alignItems:"center", gap:6, boxShadow:"0 1px 3px rgba(79,70,229,0.3)", opacity:saveMutation.isPending?0.7:1 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
              {saveMutation.isPending ? "Saving..." : "Save template"}
            </button>
          </div>
        </div>

        {/* HINT */}
        <div style={{ flexShrink:0, background:"#fffbeb", borderBottom:"1px solid #fde68a", padding:"7px 20px", fontSize:12, color:"#92400e", display:"flex", alignItems:"center", gap:6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          Design your template freely — all cells and formatting are saved exactly as you see.
          Optionally: select cells and click <strong style={{ margin:"0 3px", color:"#15803d" }}>Extract here</strong> for single values,
          or <strong style={{ margin:"0 3px", color:"#1d4ed8" }}>Repeat row</strong> for line items (AI creates one row per item).
          If you don't mark anything, the AI will intelligently extract all visible fields.
        </div>

        {/* SHEET */}
        <div style={{ flex:1, minHeight:0, padding:14, overflow:"hidden", display:"flex", flexDirection:"column" }}>
          <div style={{ flex:1, minHeight:0, border:"1px solid #e5e7eb", borderRadius:10, overflow:"hidden", boxShadow:"0 1px 8px rgba(0,0,0,0.06)", background:"#fff" }}>
            {SheetComp ? (
              <SheetComp
                initialColumns={existing?.columns ?? []}
                initialData={existingLayout}
                onSheetsChange={(data: SheetSaveData) => { sheetDataRef.current = data; }}
                height="100%"
              />
            ) : (
              <div style={{ height:"100%", display:"flex", alignItems:"center", justifyContent:"center", background:"#f9fafb" }}>
                <div style={{ textAlign:"center" }}>
                  <div style={{ width:28, height:28, border:"3px solid #e5e7eb", borderTopColor:"#4f46e5", borderRadius:"50%", margin:"0 auto 10px", animation:"spin 0.7s linear infinite" }} />
                  <p style={{ fontSize:13, color:"#9ca3af" }}>Loading spreadsheet...</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
