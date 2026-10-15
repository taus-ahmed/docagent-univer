"use client";

/**
 * The demo banner.
 *
 * Shown only when the signed-in user's own `/api/auth/me` response says
 * `is_demo` — the server computes that from DEMO_CLIENT_IDS and the JWT's
 * client_id, so with the variable unset (the default) this component renders
 * nothing for anybody, and no page needs to know whether a demo exists.
 *
 * Dismissal is per browser and remembered in localStorage: an investor who
 * closes it should not have it reappear on every navigation, and nothing about
 * it is worth a round trip or a column. A read that throws (private mode,
 * blocked site data) falls back to SHOWING the banner, which is the harmless
 * direction to be wrong in.
 */

import { useEffect, useState } from "react";
import { useAuthStore } from "@/lib/auth-store";

const DISMISS_KEY = "da_demo_banner_dismissed";

export const DEMO_BANNER_TEXT =
  "This is the PearX demo. Additional features are being built in parallel " +
  "and will appear as development continues.";

export default function DemoBanner() {
  const { user } = useAuthStore();
  const [dismissed, setDismissed] = useState(true);

  // Read the flag after mount: the server render has no localStorage, and
  // starting "dismissed" means the banner never flashes for a normal user.
  useEffect(() => {
    let stored = false;
    try {
      stored = window.localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      stored = false;
    }
    setDismissed(stored);
  }, []);

  if (!user?.is_demo || dismissed) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* a banner that cannot be remembered is still dismissed for this view */
    }
  };

  return (
    <div
      role="status"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "10px 16px",
        background: "#eef2ff",
        borderBottom: "1px solid #c7d2fe",
        color: "#3730a3",
        fontSize: 13,
        lineHeight: 1.4,
      }}
    >
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           strokeWidth="2" style={{ flexShrink: 0 }} aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <line x1="12" y1="16" x2="12" y2="12" />
        <line x1="12" y1="8" x2="12.01" y2="8" />
      </svg>
      <span style={{ flex: 1 }}>{DEMO_BANNER_TEXT}</span>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        style={{
          background: "transparent",
          border: "1px solid #c7d2fe",
          borderRadius: 6,
          color: "#3730a3",
          cursor: "pointer",
          fontSize: 12,
          padding: "3px 10px",
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
