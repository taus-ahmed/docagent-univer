"use client";

import { useEffect, useRef } from "react";
import type { TemplateColumn } from "@/lib/api";

interface Props {
  initialColumns?: TemplateColumn[];
  onSheetsChange?: (data: any[]) => void;
  height?: number | string;
}

export default function UniverSheetInner({ initialColumns = [], onSheetsChange, height = 500 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const univerRef = useRef<any>(null);
  const onChangeRef = useRef(onSheetsChange);
  onChangeRef.current = onSheetsChange;

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;

    async function init() {
      try {
        const { createUniver, defaultTheme, LocaleType, merge } = await import("@univerjs/presets");
        const { UniverSheetsCorePreset } = await import("@univerjs/preset-sheets-core");
        const UniverSheetsCorePresetEnUS = (await import("@univerjs/preset-sheets-core/locales/en-US")).default;

        if (cancelled || !containerRef.current) return;

        // Build initial cell data from columns
        const cellData: Record<number, Record<number, any>> = {};
        if (initialColumns.length > 0) {
          cellData[0] = {};
          initialColumns.forEach((col, c) => {
            cellData[0][c] = {
              v: col.name,
              t: 1,
              s: { bl: 1, fs: 11 }
            };
          });
        }

        const { univerAPI } = createUniver({
          locale: LocaleType.EN_US,
          locales: {
            [LocaleType.EN_US]: merge({}, UniverSheetsCorePresetEnUS),
          },
          theme: defaultTheme,
          presets: [
            UniverSheetsCorePreset({
              container: containerRef.current,
            }),
          ],
        });

        univerRef.current = univerAPI;

        // Create workbook
        const workbook = univerAPI.createUniverSheet({
          name: "Template",
          appVersion: "0.21.1",
          sheets: {
            sheet1: {
              id: "sheet1",
              name: "Sheet1",
              cellData,
              rowCount: 50,
              columnCount: 26,
            }
          }
        });

        // Listen for changes and report back
        univerAPI.onCommandExecuted(() => {
          if (!onChangeRef.current) return;
          try {
            const snapshot = workbook.save();
            onChangeRef.current([snapshot]);
          } catch {}
        });

      } catch (err) {
        console.error("Univer init failed:", err);
      }
    }

    init();

    return () => {
      cancelled = true;
      try { univerRef.current?.dispose?.(); } catch {}
    };
  }, []);

  return (
    <div
      ref={containerRef}
      style={{
        height: height,
        width: "100%",
        borderRadius: 10,
        overflow: "hidden",
        border: "1px solid #e3e6ec",
      }}
    />
  );
}