"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuthStore } from "@/lib/auth-store";

const NAV = [
  { href: "/extract",   label: "Extract",   icon: "extract"   },
  { href: "/history",   label: "History",   icon: "history"   },
  { href: "/templates", label: "Templates", icon: "templates" },
];
const ADMIN_NAV = [
  { href: "/analytics", label: "Analytics", icon: "analytics" },
  { href: "/admin",     label: "Admin",     icon: "admin"     },
];

function Icon({ type }: { type: string }) {
  const p = { viewBox:"0 0 24 24", fill:"none", stroke:"currentColor", strokeWidth:"2",
    strokeLinecap:"round" as const, strokeLinejoin:"round" as const, width:15, height:15 };
  if (type==="extract")   return <svg {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>;
  if (type==="history")   return <svg {...p}><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>;
  if (type==="templates") return <svg {...p}><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>;
  if (type==="analytics") return <svg {...p}><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>;
  if (type==="admin")     return <svg {...p}><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>;
  return null;
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router   = useRouter();
  const pathname = usePathname();
  const { user, isAuthenticated, logout, refreshUser, initializeFromStorage } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) { router.replace("/login"); return; }
    initializeFromStorage();
  }, [isAuthenticated]);

  if (!isAuthenticated) return null;

  const initials = user?.display_name?.split(" ").map((w:string)=>w[0]).slice(0,2).join("").toUpperCase() ?? "U";

  return (
    <div className="page-shell">
      <aside className="sidebar">
        <div className="sb-brand">
          <div className="sb-brand-icon">D</div>
          <span className="sb-brand-name">DocAgent</span>
        </div>
        <nav className="sb-nav">
          <div className="sb-group">Workspace</div>
          {NAV.map(({href,label,icon}) => (
            <Link key={href} href={href} className={`sb-item${pathname.startsWith(href)?" active":""}`}>
              <Icon type={icon}/>{label}
            </Link>
          ))}
          {user?.role==="admin" && <>
            <div className="sb-group" style={{marginTop:8}}>Admin</div>
            {ADMIN_NAV.map(({href,label,icon}) => (
              <Link key={href} href={href} className={`sb-item${pathname.startsWith(href)?" active":""}`}>
                <Icon type={icon}/>{label}
              </Link>
            ))}
          </>}
        </nav>
        <div className="sb-footer">
          <div className="sb-user">
            <div className="sb-avatar">{initials}</div>
            <div>
              <div className="sb-user-name">{user?.display_name??user?.username}</div>
              <div className="sb-user-role">{user?.role}</div>
            </div>
          </div>
          <button className="sb-signout" onClick={()=>{logout();router.replace("/login");}}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
            Sign out
          </button>
        </div>
      </aside>
      <main className="page-content">{children}</main>
    </div>
  );
}
