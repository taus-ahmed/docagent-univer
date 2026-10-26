// The template editor's keyboard rules (Part A7), kept as pure functions so
// they are tested without a browser (lib/gridKeys.test.ts).
//
// The grid used to listen on the WHOLE WINDOW: Enter on the Save button moved
// the selection instead of saving, typing anywhere edited a cell, keys reached
// the grid behind an open dialog, and Tab — unhandled — threw focus out of the
// editor while the selection stayed put. Now the grid takes keys only when
// focus is inside it and nothing sits on top of it; Tab moves between cells
// and lets focus leave at the edge, so there is never a focus trap.

export type Action =
  | { kind: "move"; dr: number; dc: number }
  | { kind: "leave" }
  | { kind: "commit"; dr: number; dc: number }
  | { kind: "cancel" }
  | { kind: "none" };

/** Tab / Shift+Tab with a cell selected (not editing). */
export function selectKey(e: { key: string; shift: boolean; col: number; cols: number }): Action {
  if (e.key !== "Tab") return { kind: "none" };
  if (!e.shift && e.col >= e.cols - 1) return { kind: "leave" };
  if (e.shift && e.col <= 0) return { kind: "leave" };
  return { kind: "move", dr: 0, dc: e.shift ? -1 : 1 };
}

/** Keys inside a cell (or the formula bar) while editing. */
export function editKey(e: { key: string; shift: boolean }): Action {
  if (e.key === "Tab") return { kind: "commit", dr: 0, dc: e.shift ? -1 : 1 };
  if (e.key === "Enter") return { kind: "commit", dr: e.shift ? -1 : 1, dc: 0 };
  if (e.key === "Escape") return { kind: "cancel" };
  return { kind: "none" };
}

/** Whether a key press is the grid's to handle at all. */
export function gridOwnsKey(s: { focusInGrid: boolean; dialogOpen: boolean; editing: boolean }): boolean {
  return s.focusInGrid && !s.dialogOpen && !s.editing;
}
