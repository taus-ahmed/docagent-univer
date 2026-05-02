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

  // Keep nameRef in sync so save can read it without stale closure
  useEffect(() => { nameRef.current = name; }, [name]);
  useEffect(() => { setMounted(true); }, []);

  useEffect(() => {
    if (!mounted) return;
    import("@/components/templates/DocAgentSpreadsheet")
      .then(m => setSheetComp(() => m.default))
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
      nameRef.current = existing.name;
      setDocType(existing.document_type);
    }
  }, [existing]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const currentName = nameRef.current.trim();
      if (!currentName) throw new Error("Enter a template name");

      // Extract columns from sheet data
      const data = sheetsRef.current;
      let cols: TemplateColumn[] = [];

      if (data?.length) {
        const sheet = data[0];
        const celldata: any[] = sheet.celldata ?? [];
        const row0 = celldata
          .filter((c: any) => c.r === 0)
          .sort((a: any, b: any) => a.c - b.c);
        cols = row0
          .map((cell: any) => String(cell.v?.v ?? "").trim())
          .filter(Boolean)
          .map((n, i) => ({ name: n, type: "Text" as const, order: i }));
      }

      if (!cols.length) throw new Error("Type at least one column name in row 1");

      const payload = { name: currentName, document_type: docType, columns: cols };
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
      {/* Fixed header - always visible */}
      <div style={{
        position: "sticky", top: 0, zIndex: 50,
        background: "#fff", borderBottom: "1px solid #e3e6ec",
        padding: "10px 0 10px", marginBottom: 10,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {/* Breadcrumb + name */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flex: 1, minWidth: 0 }}>
            <span
              style={{ fontSize: 12, color: "#9ca3af", cursor: "pointer", whiteSpace: "nowrap" }}
              onClick={() => router.push("/templates")}
            >
              Templates
            </span>
            <span style={{ color: "#d1d5db" }}>›</span>
            <input
              style={{
                fontSize: 15, fontWeight: 600, color: "#111",
                background: "#f8f9fb", border: "1.5px solid #e3e6ec",
                borderRadius: 7, outline: "none", padding: "5px 10px",
                letterSpacing: "-0.02em", minWidth: 180, flex: 1,
                transition: "border-color 0.15s",
              }}
              onFocus={e => e.currentTarget.style.borderColor = "#4f46e5"}
              onBlur={e => e.currentTarget.style.borderColor = "#e3e6ec"}
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Template name..."
              // Prevent spreadsheet keyboard handler from stealing focus
              onKeyDown={e => e.stopPropagation()}
              onKeyUp={e => e.stopPropagation()}
              onKeyPress={e => e.stopPropagation()}
            />
          </div>

          {/* Controls - always visible */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: "#6b7280" }}>
              Doc type:
              <select
                style={{ padding: "5px 8px", border: "1.5px solid #e3e6ec", borderRadius: 6, fontSize: 12, background: "#f8f9fb", outline: "none", cursor: "pointer" }}
                value={docType}
                onChange={e => setDocType(e.target.value)}
              >
                {DOC_TYPES.map(t => <option key={t}>{t}</option>)}
              </select>
            </div>
            <button
              style={{ padding: "6px 14px", borderRadius: 7, border: "1.5px solid #e3e6ec", background: "#fff", fontSize: 12, fontWeight: 500, cursor: "pointer", color: "#6b7280" }}
              onClick={() => router.push("/templates")}
            >
              Cancel
            </button>
            <button
              style={{ padding: "6px 16px", borderRadius: 7, border: "none", background: "#4f46e5", fontSize: 12, fontWeight: 600, cursor: "pointer", color: "#fff", display: "flex", alignItems: "center", gap: 5, opacity: saveMutation.isPending ? 0.7 : 1 }}
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? "Saving..." : "Save template"}
            </button>
          </div>
        </div>
      </div>

      {/* Tip */}
      <div style={{ background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 7, padding: "7px 12px", marginBottom: 10, fontSize: 12, color: "#92400e", flexShrink: 0 }}>
        Type column names in <b>Row 1</b> (e.g. Invoice Number, Vendor, Total, SKU, Price). Rows 2+ are sample data.
      </div>

      {/* Sheet - fixed height, scrolls independently */}
      <div style={{ border: "1px solid #e3e6ec", borderRadius: 10, overflow: "hidden", height: "calc(100vh - 200px)" }}>
        {SheetComp ? (
          <SheetComp
            initialColumns={existing?.columns ?? []}
            onSheetsChange={(data: any[]) => { sheetsRef.current = data; }}
            height="100%"
          />
        ) : (
          <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "#f8f9fb" }}>
            <p style={{ fontSize: 13, color: "#9ca3af" }}>Loading spreadsheet...</p>
          </div>
        )}
      </div>
    </AppLayout>
  );
}