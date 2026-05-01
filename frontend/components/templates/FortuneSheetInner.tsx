"use client";

import { useState, useRef } from "react";
import { Workbook } from "@fortune-sheet/react";
import "@fortune-sheet/react/dist/index.css";
import type { TemplateColumn } from "@/lib/api";

interface Props {
  initialColumns?: TemplateColumn[];
  onColumnsChange?: (cols: TemplateColumn[]) => void;
  height?: number;
}

export default function FortuneSheetInner({ initialColumns = [], onColumnsChange, height = 520 }: Props) {
  const onChangeRef = useRef(onColumnsChange);
  onChangeRef.current = onColumnsChange;

  const [sheets, setSheets] = useState(() => {
    const celldata = initialColumns.map((col, c) => ({
      r: 0, c,
      v: { v: col.name, m: col.name, ct: { fa: "@", t: "s" }, bl: 1 }
    }));
    return [{
      name: "Sheet1", id: "sheet1", status: 1, order: 0,
      row: 50, column: 26,
      defaultRowHeight: 25, defaultColWidth: 120,
      celldata, config: {},
    }];
  });

  function handleChange(data: any[]) {
    if (!data?.length) return;
    setSheets(data);
    const row0 = (data[0].celldata ?? [])
      .filter((c: any) => c.r === 0)
      .sort((a: any, b: any) => a.c - b.c);
    const cols: TemplateColumn[] = row0
      .map((cell: any) => String(cell.v?.v ?? cell.v?.m ?? "").trim())
      .filter(Boolean)
      .map((name: string, i: number) => ({ name, type: "Text" as const, order: i }));
    onChangeRef.current?.(cols);
  }

  const workbookProps: any = {
    data: sheets,
    onChange: handleChange,
    showToolbar: true,
    showFormulaBar: true,
    allowEdit: true,
    lang: "en",
    style: { width: "100%", height: "100%" },
  };

  return (
    <div style={{ height, border: "1px solid #e3e6ec", borderRadius: 10, overflow: "hidden" }}>
      <Workbook {...workbookProps} />
    </div>
  );
}