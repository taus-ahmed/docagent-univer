// Which controls to SHOW. The server (backend/app/core/permissions.py) is the
// authority and checks every request; this only hides what the role cannot use.
//
// The server sends `permissions` on the user (login and /api/auth/me). A
// session stored before that field existed has none, so the old rule applies:
// role "admin" sees the admin area, everyone may make templates.

export type Action =
  | "job.view" | "job.review" | "job.export" | "job.upload" | "job.cancel"
  | "job.cancel_any" | "job.delete" | "template.create" | "template.share"
  | "schema.manage" | "user.manage" | "stats.view" | "drive.use";

const ADMIN_ONLY: ReadonlySet<string> = new Set([
  "job.cancel_any", "job.delete", "schema.manage", "user.manage", "stats.view",
  "template.share",
]);

export interface PermissionSubject {
  role?: string | null;
  permissions?: readonly string[] | null;
}

export function can(user: PermissionSubject | null | undefined, action: Action): boolean {
  if (!user) return false;
  if (Array.isArray(user.permissions)) return user.permissions.includes(action);
  if (ADMIN_ONLY.has(action)) return user.role === "admin";
  return true;
}

/** The Admin / Analytics navigation: anyone who may manage users or see stats. */
export function seesAdminArea(user: PermissionSubject | null | undefined): boolean {
  return can(user, "user.manage") || can(user, "stats.view");
}

/** Cancel: the job's owner, or a role that may cancel any job in scope. */
export function mayCancel(user: (PermissionSubject & { id?: number }) | null | undefined,
                          job: { user_id?: number | null }): boolean {
  if (!user) return false;
  return can(user, "job.cancel_any") || (job.user_id != null && job.user_id === user.id);
}
