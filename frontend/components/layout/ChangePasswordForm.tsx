"use client";
import { useState } from "react";
import toast from "react-hot-toast";
import { authApi } from "@/lib/api";
import { useAuthStore } from "@/lib/auth-store";

/** Choose a new password (POST /api/auth/change-password). Shown in place of
 *  the app while the account still has its one-time password — the server
 *  refuses everything else until then (backend/app/core/auth.py). */
export default function ChangePasswordForm({ forced = false, onDone }:
    { forced?: boolean; onDone?: () => void }) {
  const setUser = useAuthStore(s => s.setUser);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const mismatch = again.length > 0 && next !== again;
  const tooShort = next.length > 0 && next.length < 12;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (mismatch || tooShort || !current) return;
    setBusy(true);
    try {
      setUser(await authApi.changePassword(current, next));
      toast.success("Password changed");
      onDone?.();
    } catch (err: any) {
      const d = err?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "The password could not be changed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card" style={{ maxWidth: 420, margin: "48px auto", padding: 24 }}>
      <h2 style={{ marginTop: 0 }}>Choose your password</h2>
      {forced && (
        <p style={{ color: "var(--text2)", fontSize: 13 }}>
          You signed in with a one-time password. Choose your own to continue.
        </p>
      )}
      <label className="form-label">Current (one-time) password</label>
      <input className="input" type="password" autoComplete="current-password"
             value={current} onChange={e => setCurrent(e.target.value)} />
      <label className="form-label" style={{ marginTop: 12 }}>New password (at least 12 characters)</label>
      <input className="input" type="password" autoComplete="new-password"
             value={next} onChange={e => setNext(e.target.value)} />
      <label className="form-label" style={{ marginTop: 12 }}>New password again</label>
      <input className="input" type="password" autoComplete="new-password"
             value={again} onChange={e => setAgain(e.target.value)} />
      {(mismatch || tooShort) && (
        <p style={{ color: "var(--red)", fontSize: 12 }}>
          {tooShort ? "At least 12 characters." : "The two new passwords differ."}
        </p>
      )}
      <button className="btn btn-primary" type="submit" style={{ marginTop: 16 }}
              disabled={busy || !current || !next || mismatch || tooShort}>
        {busy ? "Saving…" : "Change password"}
      </button>
    </form>
  );
}
