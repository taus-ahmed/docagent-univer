"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/lib/auth-store";
import toast from "react-hot-toast";

export default function LoginPage() {
  const router = useRouter();
  const { login, isLoading } = useAuthStore();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await login(username, password);
      router.replace("/extract");
    } catch {
      toast.error("Invalid username or password");
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--bg)", padding: 24 }}>
      <style>{`
        .login-card {
          width: 100%; max-width: 380px;
          background: var(--surface); border: 1px solid var(--border);
          border-radius: 16px; padding: 36px;
          animation: slideUp 0.35s cubic-bezier(0.16,1,0.3,1) forwards;
        }
        .login-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 30px; }
        .login-brand-icon {
          width: 32px; height: 32px; background: var(--accent);
          border-radius: 9px; display: grid; place-items: center;
          font-size: 15px; font-weight: 700; color: #fff;
        }
        .login-brand-name { font-size: 16px; font-weight: 600; color: var(--text1); letter-spacing: -0.02em; }
        .login-title { font-size: 22px; font-weight: 600; color: var(--text1); letter-spacing: -0.025em; margin-bottom: 4px; }
        .login-sub { font-size: 13px; color: var(--text3); margin-bottom: 26px; }
        .login-field { margin-bottom: 14px; }
        .login-label { display: block; font-size: 12px; font-weight: 500; color: var(--text2); margin-bottom: 6px; }
        .pw-wrap { position: relative; }
        .pw-toggle {
          position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
          background: none; border: none; cursor: pointer; color: var(--text3);
          padding: 2px; display: grid; place-items: center;
        }
        .pw-toggle:hover { color: var(--text1); }
        .login-submit {
          width: 100%; padding: 10px; background: var(--accent); color: #fff;
          border: none; border-radius: 8px; font-size: 14px; font-weight: 500;
          font-family: var(--font-sans); cursor: pointer; margin-top: 6px;
          transition: background 0.15s, transform 0.08s;
        }
        .login-submit:hover:not(:disabled) { background: var(--accent-hover); }
        .login-submit:active { transform: scale(0.99); }
        .login-submit:disabled { opacity: 0.5; cursor: not-allowed; }
        .login-hint { text-align: center; margin-top: 20px; font-size: 11px; color: var(--text4); }
      `}</style>

      <div className="login-card">
        <div className="login-brand">
          <div className="login-brand-icon">D</div>
          <span className="login-brand-name">DocAgent</span>
        </div>
        <h1 className="login-title">Sign in</h1>
        <p className="login-sub">AI-powered document extraction</p>

        <form onSubmit={handleSubmit}>
          <div className="login-field">
            <label className="login-label">Username</label>
            <input
              className="input"
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="admin"
              autoFocus
              autoComplete="username"
              required
            />
          </div>
          <div className="login-field">
            <label className="login-label">Password</label>
            <div className="pw-wrap">
              <input
                className="input"
                type={showPw ? "text" : "password"}
                value={password}
                onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete="current-password"
                style={{ paddingRight: 36 }}
                required
              />
              <button type="button" className="pw-toggle" onClick={() => setShowPw(p => !p)}>
                {showPw
                  ? <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                  : <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                }
              </button>
            </div>
          </div>
          <button className="login-submit" type="submit" disabled={isLoading}>
            {isLoading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="login-hint">DocAgent v2.0</p>
      </div>
    </div>
  );
}
