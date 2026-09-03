"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { templatesApi, type TemplateColumn, type ColumnTemplate,
         type ShapePreview } from "@/lib/api";
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
  const [sheetReady, setSheetReady] = useState(false);

  // sheetDataRef holds the latest data from the spreadsheet.
  // It is pre-populated from existingLayout when the template data arrives
  // so that save works even if the user hasn't interacted with the sheet yet.
  const sheetDataRef = useRef<SheetSaveData | null>(null);

  // THE SAVE GATE. The engine's own verdict on the current grid, pushed up by
  // the spreadsheet. `slotCount` was already computed and rendered inside that
  // component and was simply unreachable from here, so a template the engine
  // cannot fill saved without complaint and failed later, per document, with
  // its real reason landing in a field the UI never read.
  //
  // The numbers are NOT re-derived in TypeScript. That would be a second
  // implementation of the rule, which is what retiring `extractTarget` was
  // about; the editor asks the server and shows what it says.
  const [shape, setShape] = useState<ShapePreview | null>(null);
  const nameRef = useRef("");
  const autoNameRef = useRef("Template-1");

  useEffect(() => { nameRef.current = name; }, [name]);
  useEffect(() => { setMounted(true); }, []);

  // Load the spreadsheet component dynamically (only on client)
  useEffect(() => {
    if (!mounted) return;
    if (!isAuthenticated) { router.replace("/login"); return; }
    import("@/components/templates/DocAgentSpreadsheet")
      .then(m => setSheetComp(() => m.default))
      .catch(console.error);
  }, [mounted, isAuthenticated]);

  // Fetch all templates to generate auto-name for new templates
  const { data: allTemplates } = useQuery({
    queryKey: ["templates"],
    queryFn: () => templatesApi.list(),
    enabled: !templateId,
  });

  // Auto-generate default name for new templates
  useEffect(() => {
    if (templateId) return;
    if (name) return;
    const existingNums = (allTemplates ?? [])
      .map((t: any) => { const m = t.name?.match(/^Template-(\d+)$/); return m ? parseInt(m[1]) : 0; })
      .filter((n: number) => n > 0);
    const nextNum = existingNums.length > 0 ? Math.max(...existingNums) + 1 : 1;
    const defaultName = `Template-${nextNum}`;
    setName(defaultName);
    nameRef.current = defaultName;
    autoNameRef.current = defaultName;
  }, [allTemplates, templateId]);

  // Fetch existing template when editing
  const { data: existing } = useQuery<ColumnTemplate>({
    queryKey: ["template", templateId],
    queryFn: () => templatesApi.get(templateId!),
    enabled: !!templateId,
    // Keep data fresh — this ensures it's available when SheetComp loads
    staleTime: 0,
  });

  // Populate name and doc type from existing template
  useEffect(() => {
    if (!existing) return;
    setName(existing.name);
    nameRef.current = existing.name;
    const isStandard = DOC_TYPES.some(t => t.value === existing.document_type && t.value !== "other");
    if (isStandard) { setDocType(existing.document_type); }
    else { setDocType("other"); setCustomDocType(existing.document_type); }
  }, [existing]);

  // Parse existing template's saved layout from description field
  const existingLayout = (() => {
    if (!existing?.columns) return null;
    try {
      const desc = (existing as any).description;
      if (desc) return JSON.parse(desc) as SheetSaveData;
    } catch {}
    return null;
  })();

  // FIX 1: Pre-populate sheetDataRef from existingLayout as soon as it's available.
  // This means save works immediately when the user opens an existing template
  // even before they interact with the spreadsheet.
  useEffect(() => {
    if (existingLayout && sheetDataRef.current === null) {
      sheetDataRef.current = existingLayout;
    }
  }, [existingLayout]);

  // FIX 2: Track when the sheet component has called onSheetsChange at least once.
  // We use this to show a ready indicator and to know the ref is populated.
  const handleSheetsChange = useCallback((data: SheetSaveData) => {
    sheetDataRef.current = data;
    setSheetReady(true);
  }, []);

  // FIX 3: When SheetComp loads and we have existingLayout, wait for the sheet
  // to fully initialize before allowing saves. We do this by setting a short
  // timeout that marks the sheet as ready if no onSheetsChange has fired yet.
  useEffect(() => {
    if (!SheetComp) return;
    const timer = setTimeout(() => {
      // If the sheet component loaded but never called onSheetsChange
      // (can happen with empty new templates), still allow saving
      setSheetReady(true);
      // Also ensure ref is populated for existing templates
      if (sheetDataRef.current === null && existingLayout) {
        sheetDataRef.current = existingLayout;
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [SheetComp, existingLayout]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const n = nameRef.current.trim();
      if (!n) throw new Error("Please enter a template name");

      const finalDocType = docType === "other"
        ? (customDocType.trim() || "other")
        : docType;

      // FIX: Use existingLayout as fallback if sheetDataRef is still null.
      // This handles the case where the user opens a template and immediately
      // clicks Save without interacting with the spreadsheet.
      const sheetData = sheetDataRef.current ?? existingLayout;

      if (!sheetData) {
        throw new Error("Spreadsheet is still loading — please wait a moment and try again");
      }

      // Check if there are any cells with content
      const hasCells = Object.values(sheetData.cells ?? {}).some((c: any) => c?.value?.trim());
      if (!hasCells) throw new Error("Add some content to the spreadsheet before saving");

      // BLOCK a template the engine cannot fill, carrying ITS message rather
      // than a paraphrase. `shape` is null only when the preview call failed,
      // and a save is not the moment to guess — let it through, and let
      // extraction report honestly if it really is unusable.
      if (shape && shape.usable === false) {
        throw new Error(shape.error
          ?? "This template has no slots to fill. Leave a cell empty next to "
             + "a label, or put column headings in a row with empty rows beneath.");
      }

      // Build the columns list from the one rule (Phase 2a): a slot is an empty
      // cell, and its name is the nearest label to its left (then above). The
      // server derives the authoritative shape from the same grid; this list is
      // only the flat column summary the template API stores alongside it.
      let cols: TemplateColumn[] = [];

      const cellsMap: Record<string, any> = sheetData.cells ?? {};
      const txt = (r: number, c: number) => (cellsMap[`${r},${c}`]?.value ?? "").trim();
      let boxR = -1, boxC = -1;
      Object.entries(cellsMap).forEach(([k, cell]: any) => {
        if (!cell?.value?.trim()) return;
        const [r, c] = k.split(",").map(Number);
        if (r > boxR) boxR = r;
        if (c > boxC) boxC = c;
      });
      const repeatRows = new Set<number>(sheetData.repeatRows ?? []);
      const slotCols: TemplateColumn[] = [];
      for (let r = 0; r <= boxR; r++) {
        for (let c = 0; c <= boxC; c++) {
          if (!(`${r},${c}` in cellsMap) || txt(r, c)) continue;
          let label = "";
          for (let dc = 1; dc <= 3 && !label; dc++) label = txt(r, c - dc);
          if (!label) for (let dr = 1; dr <= 3 && !label; dr++) label = txt(r - dr, c);
          if (!label) continue;
          slotCols.push({
            name: label,
            type: "Text" as const,
            order: slotCols.length,
            extraction_type: repeatRows.has(r) ? "lineitem" : "header",
          });
        }
      }

      if (slotCols.length > 0) {
        cols = slotCols;
      } else {
        const cellEntries = Object.entries(sheetData.cells ?? {});
        const allNamedCells = cellEntries
          .filter(([, cell]: any) => cell?.value?.trim())
          .map(([key, cell]: any) => {
            const [r, c] = key.split(",").map(Number);
            return { r, c, value: cell.value.trim() };
          })
          .sort((a: any, b: any) => a.r - b.r || a.c - b.c);

        cols = allNamedCells.map((cell: any, i: number) => ({
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
      // WARN, do not block, on a partial read. A notes column the engine will
      // never fill is a legitimate thing to draw, and blocking it would be a
      // new version of the bug this gate exists to fix — the save path
      // deciding it knows better than the person drawing the template.
      const cov = shape?.coverage;
      if (cov && !cov.complete) {
        const bits: string[] = [];
        if (cov.orphan_count) {
          const names = cov.orphan_labels.slice(0, 3)
            .map(o => `"${o.label}"`).join(", ");
          bits.push(`${cov.orphan_count} label${cov.orphan_count === 1 ? "" : "s"} `
                    + `with nowhere to put a value (${names}`
                    + `${cov.orphan_count > 3 ? ", …" : ""})`);
        }
        if (cov.skipped?.length) bits.push(cov.skipped[0]);
        if (bits.length) toast(`Saved, but the engine could not read all of it: ${bits.join("; ")}`,
                               { icon: "⚠️", duration: 8000 });
      }
      router.push("/templates");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // FIX: Don't render SheetComp until we have existing data for edit mode.
  // This prevents the blank sheet flash — we wait for the data before
  // mounting the spreadsheet so it initializes with the correct content.
  const canRenderSheet = SheetComp && (
    !templateId ||           // new template: render immediately
    existing !== undefined   // edit template: wait for data
  );

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
          {[
            { href:"/extract",   label:"Extract"   },
            { href:"/history",   label:"History"   },
            { href:"/templates", label:"Templates", active:true },
          ].map(item => (
            <Link key={item.href} href={item.href}
              style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 10px", borderRadius:6, fontSize:13,
                color:(item as any).active ? "#818cf8" : "#8b90ae",
                background:(item as any).active ? "rgba(79,70,229,0.2)" : "transparent",
                marginBottom:2, textDecoration:"none",
                fontWeight:(item as any).active ? 500 : 400 }}>
              {item.label}
            </Link>
          ))}
          {user?.role === "admin" && (
            <>
              <div style={{ fontSize:10, fontWeight:700, textTransform:"uppercase" as const, letterSpacing:"0.08em", color:"#555a7a", padding:"12px 10px 8px" }}>Admin</div>
              {[{ href:"/analytics", label:"Analytics" }, { href:"/admin", label:"Admin" }].map(item => (
                <Link key={item.href} href={item.href}
                  style={{ display:"flex", alignItems:"center", gap:8, padding:"8px 10px", borderRadius:6, fontSize:13, color:"#8b90ae", marginBottom:2, textDecoration:"none" }}>
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
          <button onClick={() => { logout(); router.replace("/login"); }}
            style={{ background:"transparent", border:"none", color:"#8b90ae", cursor:"pointer", fontSize:11, padding:4 }}>
            Sign out
          </button>
        </div>
      </aside>

      {/* MAIN */}
      <div style={{ flex:1, display:"flex", flexDirection:"column", overflow:"hidden", minWidth:0 }}>
        {/* TOP BAR */}
        <div style={{ flexShrink:0, background:"#fff", borderBottom:"1px solid #e5e7eb", height:56, display:"flex", alignItems:"center", padding:"0 20px", gap:10, boxShadow:"0 1px 3px rgba(0,0,0,0.05)" }}>
          <span onClick={() => router.push("/templates")}
            style={{ fontSize:13, color:"#9ca3af", cursor:"pointer", whiteSpace:"nowrap", flexShrink:0 }}>
            Templates
          </span>
          <span style={{ color:"#d1d5db", flexShrink:0 }}>›</span>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Untitled template"
            onKeyDown={e => e.stopPropagation()}
            onKeyUp={e => e.stopPropagation()}
            style={{ flex:1, minWidth:0, fontSize:15, fontWeight:600, color:"#111", background:"transparent", border:"none", outline:"none", fontFamily:"inherit" }}
          />
          <div style={{ display:"flex", alignItems:"center", gap:8, flexShrink:0 }}>
            <span style={{ fontSize:12, color:"#6b7280", whiteSpace:"nowrap" }}>Document type:</span>
            <select
              value={docType}
              onChange={e => { setDocType(e.target.value); if (e.target.value !== "other") setCustomDocType(""); }}
              style={{ padding:"5px 8px", border:"1px solid #e5e7eb", borderRadius:6, fontSize:12, background:"#f9fafb", color:"#374151", outline:"none", cursor:"pointer", fontFamily:"inherit" }}>
              {DOC_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            {docType === "other" && (
              <input
                value={customDocType}
                onChange={e => setCustomDocType(e.target.value)}
                placeholder="e.g. pay_order"
                onKeyDown={e => e.stopPropagation()}
                onKeyUp={e => e.stopPropagation()}
                style={{ padding:"5px 10px", border:"1px solid #a5b4fc", borderRadius:6, fontSize:12, background:"#f0f0ff", color:"#374151", outline:"none", fontFamily:"inherit", width:150 }}
              />
            )}
            <button
              onClick={() => router.push("/templates")}
              style={{ padding:"6px 14px", borderRadius:7, border:"1px solid #e5e7eb", background:"#fff", fontSize:13, fontWeight:500, cursor:"pointer", color:"#6b7280", fontFamily:"inherit" }}>
              Cancel
            </button>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              style={{ padding:"7px 18px", borderRadius:7, border:"none", background:"#4f46e5", fontSize:13, fontWeight:600,
                cursor:saveMutation.isPending ? "not-allowed" : "pointer",
                color:"#fff", fontFamily:"inherit", display:"flex", alignItems:"center", gap:6,
                boxShadow:"0 1px 3px rgba(79,70,229,0.3)", opacity:saveMutation.isPending ? 0.7 : 1 }}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                <polyline points="17 21 17 13 7 13 7 21"/>
                <polyline points="7 3 7 8 15 8"/>
              </svg>
              {saveMutation.isPending ? "Saving..." : "Save template"}
            </button>
          </div>
        </div>

        {/* HINT BAR */}
        <div style={{ flexShrink:0, background:"#fffbeb", borderBottom:"1px solid #fde68a", padding:"7px 20px", fontSize:12, color:"#92400e", display:"flex", alignItems:"center", gap:6 }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          Type a label in a cell to make it a heading; leave the cell beside it{" "}
          <strong style={{ margin:"0 3px", color:"#15803d" }}>empty</strong>
          {" "}and the AI fills that cell. Empty cells are shown in green.
          For line items, put your column headings in a row and leave the rows
          beneath them empty — the AI adds one row per item.
        </div>

        {/* SHAPE — what the engine derived from this grid. Read-only on purpose:
            the grid is the single source of truth, so it is corrected by editing
            cells rather than by overriding the shape here. */}
        {existing?.shape?.summary && (
          <div style={{ flexShrink:0, background:"#f8f9fb", borderBottom:"1px solid #e5e7eb", padding:"6px 20px", fontSize:11.5, color:"#4b5563", display:"flex", alignItems:"center", gap:8 }}>
            <span style={{ fontWeight:600, color:"#374151" }}>Structure:</span>
            <span style={{ fontFamily:"'JetBrains Mono',monospace", fontSize:11 }}>{existing.shape.summary}</span>
            <span style={{ color:"#9ca3af" }}>— edit cells to change this</span>
          </div>
        )}

        {/* SPREADSHEET */}
        <div style={{ flex:1, minHeight:0, padding:14, overflow:"hidden", display:"flex", flexDirection:"column" }}>
          <div style={{ flex:1, minHeight:0, border:"1px solid #e5e7eb", borderRadius:10, overflow:"hidden", boxShadow:"0 1px 8px rgba(0,0,0,0.06)", background:"#fff" }}>
            {canRenderSheet ? (
              <SheetComp
                initialColumns={existing?.columns ?? []}
                initialData={existingLayout}
                onSheetsChange={handleSheetsChange}
                onShapeChange={setShape}
                height="100%"
              />
            ) : (
              <div style={{ height:"100%", display:"flex", alignItems:"center", justifyContent:"center", background:"#f9fafb" }}>
                <div style={{ textAlign:"center" }}>
                  <div style={{ width:28, height:28, border:"3px solid #e5e7eb", borderTopColor:"#4f46e5", borderRadius:"50%", margin:"0 auto 10px", animation:"spin 0.7s linear infinite" }} />
                  <p style={{ fontSize:13, color:"#9ca3af" }}>
                    {!SheetComp ? "Loading spreadsheet..." : "Loading template data..."}
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
