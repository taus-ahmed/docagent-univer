// AUTH-ADJACENT. When a protected page may render, and where login sends you.
//
// The layout used to decide on the store's INITIAL state: `isAuthenticated`
// starts false, so a reload or a pasted link (/extract?job=12) redirected to
// /login before the token in localStorage had been read at all. The decision
// now waits until the stored session has been read (`initialized`), and only
// then allows or redirects. Nothing about how the token is stored, validated
// or refreshed changes; a page with no valid session is still redirected.
//
// No imports, so `node --test` can run it.

export type Gate = "wait" | "allow" | "redirect";

export function gateDecision(initialized: boolean, authenticated: boolean): Gate {
  if (!initialized) return "wait";
  return authenticated ? "allow" : "redirect";
}

/** The rule `isTokenValid` in lib/api.ts applies, given its inputs. */
export function tokenValid(token: string | null, exp: string | null, now: number): boolean {
  if (!token) return false;
  if (!exp) return true;
  return now < parseInt(exp);
}

/** /login, carrying the page asked for so login can return to it. */
export function loginUrl(pathname: string, search: string): string {
  const here = (pathname || "/") + (search || "");
  if (!pathname || pathname === "/" || pathname.startsWith("/login")) return "/login";
  return "/login?next=" + encodeURIComponent(here);
}

/** Where to go after login: a same-site path only, never another origin. */
export function safeNext(raw: string | null | undefined): string {
  const fallback = "/extract";
  if (!raw) return fallback;
  let next: string;
  try { next = decodeURIComponent(raw); } catch { return fallback; }
  if (!next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")
      || next.startsWith("/login") || /[\r\n]/.test(next)) return fallback;
  return next;
}
