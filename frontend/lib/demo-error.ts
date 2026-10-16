/**
 * What a demo user is told when something fails.
 *
 * A demo audience should not read "This template has no slots to fill", a
 * stack-trace fragment, or an HTTP status — but it SHOULD still read the
 * sentences the demo wrote on purpose ("This looks like a scanned document…",
 * "Uploads are disabled in this demo…"), which are explanations rather than
 * errors. The backend tells the two apart by tagging its own deliberate
 * refusals with the `X-Demo-Notice` header (`app/core/demo.py`), so the only
 * thing decided here is which of the two to show.
 *
 * Nothing is suppressed server-side: the real error is still logged and still
 * stored on the job exactly as before. This is a display rule, and it is off
 * for every non-demo user.
 */

export const DEMO_GENERIC_ERROR =
  "Something went wrong with this document. Please try another one, or use a sample document.";

/**
 * Clicking one of the "Additional Options" cards in the demo. The cards stay
 * visible and unchanged — an investor should see what the product does — but
 * they do not turn on, because categorisation, charts, the AI summary and
 * anomaly detection are still being built. The backend forces them off too
 * (`app/core/demo.py::filter_options`); this is only what the click says.
 */
export const DEMO_OPTION_UNAVAILABLE =
  "Sorry, we're developing this feature right now. It isn't available in the demo.";

const DEMO_NOTICE_HEADER = "x-demo-notice";

/** The text to show for a failed API call. */
export function apiErrorText(
  err: any,
  { isDemo, fallback }: { isDemo: boolean; fallback: string },
): string {
  const detail = err?.response?.data?.detail;
  const asText = typeof detail === "string" && detail ? detail : null;
  if (!isDemo) return asText ?? fallback;

  // A refusal the demo meant to show: pass it through verbatim.
  const headers = err?.response?.headers;
  const tagged = Boolean(
    headers?.[DEMO_NOTICE_HEADER] ?? headers?.get?.(DEMO_NOTICE_HEADER),
  );
  return tagged && asText ? asText : DEMO_GENERIC_ERROR;
}

/**
 * The text to show for a job that failed or partly failed. The stored
 * `error_message` is written for whoever is debugging the pipeline, so a demo
 * user gets the neutral sentence instead — always, since there is no header to
 * consult on a value read out of the job row.
 */
export function jobErrorText(
  message: string | null | undefined,
  isDemo: boolean,
): string | null {
  if (!message) return null;
  return isDemo ? DEMO_GENERIC_ERROR : message;
}
