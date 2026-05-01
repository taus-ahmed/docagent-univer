"use client";
import dynamic from "next/dynamic";
import type { TemplateColumn } from "@/lib/api";

const FortuneSheetEditor = dynamic(
  () => import("./FortuneSheetInner"),
  { 
    ssr: false,
    loading: () => (
      <div style={{ height: 520, display: "flex", alignItems: "center", justifyContent: "center", background: "#f8f9fb", border: "1px solid #e3e6ec", borderRadius: 10 }}>
        <p style={{ fontSize: 13, color: "#9ca3af" }}>Loading spreadsheet...</p>
      </div>
    )
  }
);

export default FortuneSheetEditor;