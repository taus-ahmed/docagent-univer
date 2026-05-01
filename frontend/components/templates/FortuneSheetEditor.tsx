"use client";
import dynamic from "next/dynamic";

const UniverSheet = dynamic(
  () => import("./UniverSheetInner"),
  {
    ssr: false,
    loading: () => (
      <div style={{ height: "100%", minHeight: 500, display: "flex", alignItems: "center", justifyContent: "center", background: "#f8f9fb", border: "1px solid #e3e6ec", borderRadius: 10 }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ width: 32, height: 32, border: "3px solid #e3e6ec", borderTopColor: "#4f46e5", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
          <p style={{ fontSize: 13, color: "#9ca3af" }}>Loading spreadsheet...</p>
        </div>
      </div>
    )
  }
);

export default UniverSheet;