// Run Q, UI2: where notifications appear, in one place.
//
// Toasts used to appear top-right, which is exactly where the review dialog
// puts "Mark document reviewed": the "Document marked reviewed" notice sat
// over the button for four seconds and blocked it. Every action button in
// the app sits in a header or a toolbar; the bottom-right corner holds none.
// The region is fixed (react-hot-toast renders it position:fixed), so a toast
// never shifts the layout.

export const TOAST_POSITION = "bottom-right" as const;

/** Auto-dismiss after about three seconds; an error stays a little longer. */
export const TOAST_DURATION_MS = 3000;
export const TOAST_ERROR_DURATION_MS = 5000;

/** Offset from the viewport edge, so a toast never sits on a scrollbar or a
 *  bottom-anchored button row. */
export const TOAST_GUTTER_PX = 16;

export const TOAST_CONTAINER_STYLE = {
  bottom: TOAST_GUTTER_PX,
  right: TOAST_GUTTER_PX,
  pointerEvents: "none" as const,
};

/** The inline confirmation shown next to a button that has just succeeded,
 *  so the state is visible where the user is looking and not only in a toast. */
export function inlineConfirmation(reviewed: boolean, justDone: boolean): string {
  if (justDone) return "Reviewed";
  return reviewed ? "Reviewed" : "";
}
