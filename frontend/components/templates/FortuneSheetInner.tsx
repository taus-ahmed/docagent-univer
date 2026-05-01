"use client";

import { useRef, useState } from "react";
import { Workbook } from "@fortune-sheet/react";
import "@fortune-sheet/react/dist/index.css";
import type { TemplateColumn } from "@/lib/api";

interface Props {
  initialColumns?: TemplateColumn[];
  onSheetsChange?: (data: any[]) => void;
  height?: number | string;
}

export default function FortuneSheetInner({ initialColumns = [], onSheetsChange, height = 480 }: Props) {
  const onChangeRef = useRef(onSheetsChange);
  onChangeRef.current = onSheetsChange;

  const [sheets] = useState(() => {
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

  const props: any = {
    data: sheets,
    onChange: (data: any[]) => { onChangeRef.current?.(data); },
    showToolbar: true,
    showFormulaBar: true,
    allowEdit: true,
    lang: "en",
    style: { width: "100%", height: "100%" },
  };

  return (
    <div style={{ height, border: "1px solid #e3e6ec", borderRadius: 10, overflow: "hidden" }}>
      <Workbook {...props} />
    </div>
  );
}