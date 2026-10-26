# Roles: what the routes allow today, and a recommended matrix

**Status:** steps 1, 2, 4 and 5 below are IMPLEMENTED (round 12/13):
`backend/app/core/permissions.py` holds the matrix as data and every route asks
`can(user, action, resource)`; `role = "reviewer"` exists (the column is a plain
`String(20)`, so no migration); another tenant's job answers 404. **Open:** step 3
(explicit `platform_admin` role — a data migration; until then platform_admin is
derived from "admin with no client_id" exactly as before). The inventory below
is the one taken 2026-10-23 before the change; line numbers are at that commit,
and each finding that has since been resolved is marked **[resolved]**.

### As implemented

| Capability | platform_admin | tenant_admin | company_admin (legacy) | reviewer | user |
|---|---|---|---|---|---|
| Upload documents | ✓ (names a tenant) | ✓ | ✓ | ✓ | ✓ |
| View / review / edit / export results | all tenants | own tenant | own tenant | own tenant | own jobs |
| Cancel a job | any | own tenant | own tenant | own jobs | own jobs |
| Hard-delete a job | any | own tenant | own jobs | own jobs | own jobs |
| Templates: create / edit own | ✓ | ✓ | ✓ | — | ✓ |
| Templates: share, edit the firm's | ✓ | ✓ | ✓ | — | — |
| Schemas, users, system statistics | all tenants | own tenant | — | — | — |
| Watch folders | all | own tenant | own | own | own |

Decisions taken: `company_admin` keeps exactly its old powers (it is still
assignable only through `PUT /api/admin/users`), **including cancelling any
job of its own firm** (`job.cancel_any`; briefly removed in round 13 and
restored in Run 15 after review — another firm's job still answers 404);
cancelling someone else's job otherwise needs an admin; an unknown stored role string acts as
`user`, as the inline checks did; `UserUpdate.role` is now validated against the
known role values. The UI reads `permissions` from `/api/auth/me` to hide
controls (`frontend/lib/permissions.ts`); the server checks every request.

## The roles that exist today

There is no role table; three checks are spelled inline in many places.

| Who | How the code recognises them | Where it is enforced |
|---|---|---|
| **super-admin** | `role == "admin"` and no `client_id` | `admin.py:194 _is_super_admin`, `schemas.py:34`, `export.py:35`, `extract.py:7068`, `templates.py:33,72,271` |
| **tenant admin** | `role == "admin"` with a `client_id` | `require_admin` (`auth.py:146`) admits it; queries then filter by `client_id` (`admin.py`, `schemas.py`) |
| **company_admin** | `role == "company_admin"` | jobs of the whole tenant (`extract.py:6771, 7071`), shared templates (`templates.py:195, 225, 277`); **rejected by `require_admin`**, so it cannot manage users or schemas. Cannot be assigned through the API (`schemas.py:43` allows `admin|client` only) |
| **client** (user) | anything else | own jobs only (`_get_job_or_404`, `extract.py:7075`) |
| demo user | `is_demo_user` (a tenant flag, orthogonal to role) | sample documents, no Drive, history cutoff, no provenance in exports |

## Every route, and who may call it today

"Job access" = `_get_job_or_404`: super-admin any job; admin or company_admin
with a `client_id`, any job of that tenant; anyone else, jobs they created.
Another tenant's job answers **403** on the job routes and **404** on the review
routes (`review.py:51`).

| Method | Path | File | Today |
|---|---|---|---|
| POST | /api/auth/login | auth.py:83 | anyone (rate limited per IP) |
| GET | /api/auth/me | auth.py:157 | any signed-in user |
| PUT | /api/auth/me | auth.py:172 | any signed-in user (own profile, password) |
| POST | /api/auth/logout | auth.py:203 | anyone (no server effect) |
| POST | /api/extract/upload | extract.py:561 | any signed-in user; tenant from token, super-admin names one |
| GET | /api/jobs | extract.py:6763 | own jobs; tenant's jobs for admin/company_admin; all for super-admin |
| GET | /api/jobs/{id} | extract.py:6783 | job access |
| GET | /api/jobs/{id}/results | extract.py:6787 | job access |
| GET | /api/jobs/{id}/inferred-templates | extract.py:6811 | job access |
| PUT | /api/jobs/{id}/docs/{doc} | extract.py:7009 | job access — **edits values** |
| PATCH | /api/jobs/{id}/docs/{doc}/fields/{ref} | extract.py:7022 | job access — **edits a value** |
| POST | /api/jobs/{id}/docs/{doc}/approve | extract.py:7039 | job access — **marks reviewed** |
| DELETE | /api/jobs/{id} | extract.py:7049 | job access — cancels a running job (deletes nothing) |
| GET | /api/jobs/{id}/export | extract.py:4345 | job access |
| GET | /api/jobs/{id}/export/zip | extract.py:4429 | job access |
| POST | /api/export/combined | export.py:43 | job access; template by tenant |
| POST | /api/export/perfile | export.py:102 | job access; template by tenant |
| GET | /api/review/reasons | review.py:72 | any signed-in user |
| GET | /api/jobs/{id}/review | review.py:95 | job access (404 across tenants) |
| POST | /api/jobs/{id}/docs/{doc}/review | review.py:140 | job access — **accept / edit** |
| GET | /api/jobs/{id}/docs/{doc}/pages/{n} | review.py:308 | job access |
| GET | /api/jobs/{id}/docs/{doc}/pages/{n}/image | review.py:362 | job access |
| GET | /api/templates | templates.py:25 | tenant's + shared + defaults; all for super-admin |
| GET | /api/templates/{id} | templates.py:61 | same |
| POST | /api/templates/shape | templates.py:91 | any signed-in user (pure computation) |
| POST | /api/templates | templates.py:165 | any signed-in user; `is_shared` only for admin/company_admin |
| PUT | /api/templates/{id} | templates.py:203 | owner; admin/company_admin of the tenant; super-admin (`_get_template_or_403`, templates.py:266) |
| DELETE | /api/templates/{id} | templates.py:233 | owner; admin/company_admin of the tenant; super-admin |
| GET | /api/schemas | schemas.py:37 | own tenant's; all for super-admin |
| POST | /api/schemas | schemas.py:63 | `require_admin`; tenant admin only for its own `client_id` |
| GET | /api/schemas/{client_id} | schemas.py:135 | own tenant; super-admin any |
| DELETE | /api/schemas/{client_id} | schemas.py:171 | `require_admin`, scoped to own tenant |
| GET | /api/drive/auth/status | drive.py:84 | any signed-in user |
| POST | /api/drive/auth | drive.py:97 | any signed-in user (not demo) |
| GET | /api/drive/folders/{id} | drive.py:127 | any signed-in user (not demo) |
| POST | /api/drive/extract | drive.py:167 | any signed-in user (not demo) |
| GET | /api/watch | drive.py:267 | own folders; **every** folder for any `role == "admin"` |
| POST | /api/watch | drive.py:279 | any signed-in user (not demo) |
| DELETE | /api/watch/{id} | drive.py:321 | owner, or **any** `role == "admin"` |
| POST | /api/watch/check | drive.py:339 | any signed-in user (not demo) |
| GET | /api/admin/users | admin.py:26 | `require_admin`, tenant-scoped |
| POST | /api/admin/users | admin.py:39 | `require_admin`; tenant admin only into its own tenant |
| PUT | /api/admin/users/{id} | admin.py:76 | `require_admin`, tenant-scoped; cannot change own role |
| DELETE | /api/admin/users/{id} | admin.py:120 | `require_admin`, tenant-scoped |
| GET | /api/admin/stats | admin.py:142 | `require_admin`, tenant-scoped |
| GET | /api/demo/sample-docs | demo.py:42 | demo users |
| GET | /api/demo/sample-docs/{f}/download | demo.py:53 | demo users |
| POST | /api/demo/sample-docs/{f}/extract | demo.py:62 | demo users |

## Routes that do not fit any coherent rule

1. **[resolved, round 13; Drive itself gated by `DRIVE_TENANT` in round 14]**
   **Watch folders cross the tenant boundary** — `drive.py:274` lists every
   tenant's watch folders to any `role == "admin"`, and `drive.py:331` lets any
   admin delete any tenant's folder. A tenant admin is an admin, so tenant A's
   admin sees tenant B's Drive folder ids and can stop B's watch. **This is a
   tenancy defect, not only a role question; it should be fixed first** (scope
   both to `client_id` unless super-admin). Not changed in this round, as asked.
2. **[decided: kept as the legacy firm-wide role with its old powers,
   including cancelling any job of its firm — Run 15]**
   **`company_admin` is half a role** — it reads the whole tenant's jobs and
   shares templates, but `require_admin` refuses it, and the API cannot assign
   it (`schemas.py:43`). Nobody can create one except by SQL.
3. **Anyone who can see a job can edit and approve it** (`extract.py:7009,
   7022, 7039`, `review.py:140`). There is no read-only role: an auditor or a
   client's staff member who should only download cannot be given access.
4. **[resolved, round 13; every route since round 14 — the isolation suite]**
   **403 versus 404** across tenants on the job routes (`extract.py:7077`)
   tells a caller that a job id exists in another tenant; the review routes
   already answer 404.
5. **Tenant admin and super-admin are the same `role` string**, told apart by
   the absence of `client_id`. One `UPDATE users SET client_id = NULL` turns a
   tenant admin into a platform administrator.
6. **[resolved, rounds 13/14: `DELETE /api/jobs/{id}/data?confirm=true` for the
   owner, firm admin and platform admin; `DATA_RETENTION_DAYS`]**
   **Nothing deletes data** (see `retention.md`): no role can remove a job, a
   result or an uploaded file through the API.

## Recommended matrix

| Capability | platform_admin | tenant_admin | reviewer | user |
|---|---|---|---|---|
| Upload documents | ✓ (names a tenant) | ✓ | ✓ | ✓ |
| View results | all tenants | own tenant | own tenant | own jobs |
| Review / accept / edit values | ✓ | ✓ | ✓ | own jobs |
| Export | ✓ | ✓ | ✓ | own jobs |
| Manage users | all tenants | own tenant (not platform_admin) | — | — |
| Manage schemas | all tenants | own tenant | — | — |
| Manage templates | ✓ | own tenant, shared | own (not shared) | own |
| Drive / watch folders | ✓ | own tenant | own | own |
| System statistics | all tenants | own tenant | — | — |
| Delete data (job, results, files) | ✓ | own tenant | — | own jobs (implemented, round 14) |

`reviewer` is the role the first customer asks for: a second accountant who
checks values across the firm's jobs without managing users. A read-only
`viewer` can be added the same way later if a client asks.

## Minimal change path

1. **Fix the watch-folder scoping** (item 1) on its own, with a test that tenant
   A's admin cannot list or delete tenant B's folder. No schema change.
2. **One permission function**: `app/core/permissions.py` with
   `can(user, action, resource) -> bool` and the matrix above as data; replace
   the inline `role ==` checks route by route, each with a test, behaviour
   unchanged at first (today's roles map: super-admin → platform_admin,
   admin+client_id → tenant_admin, company_admin → reviewer, client → user).
3. **Make the platform role explicit**: `role = "platform_admin"` rather than
   "admin without a client_id". This is a data change (an UPDATE of existing
   super-admins) — needs a migration and a decision; until then `can` derives
   it exactly as today.
4. **Let the API assign the roles** (`UserCreate.role` pattern), with a rule
   that only a platform_admin creates a platform_admin.
5. **Answer 404** for another tenant's job on every job route.

Steps 1, 2, 4 and 5 need no migration; step 3 does. Product decision needed:
whether `user` may edit values on their own jobs or only the reviewer may
(the matrix above keeps today's behaviour: yes).
