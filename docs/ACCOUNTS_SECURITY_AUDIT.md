# Accounts and security audit

Date: 2026-11-19

Scope: a read-only source audit of `backend/` and `frontend/`, plus local,
offline FastAPI `TestClient` tests. No deployed service, remote storage, model,
or identity provider was contacted. Secret-bearing files and secret values were
not inspected or reproduced. Application code was not changed.

## Executive result

The application has a centralized role matrix and consistent tenant scoping for
the persistent API routes. Two ordinary users in separate firms were created
with separate jobs, documents, templates, schemas, watch folders, and stored
files. User B then tried all 27 persistent path-id routes using user A's ids.
Every response was indistinguishable from the response for a missing id, and
user A's data survived unchanged: **0 of 27 routes leaked across firms**. The
route inventory and the probes are pinned in
[`tests/test_tenant_isolation.py`](../tests/test_tenant_isolation.py) and the
broader admin/reviewer/user, list, body-id, query-id, Drive, export, and download
coverage is in
[`tests/http/test_tenant_isolation_all_routes.py:58`](../tests/http/test_tenant_isolation_all_routes.py#L58).

This is good application-level tenant isolation, but it is not yet the complete
security package most accounting firms will require. The largest gaps are an
ordinary-tenant audit log, MFA/SSO, revocable sessions, verified backups, and a
contract-ready retention/offboarding process.

## Roles and permissions

The stored roles are `admin`, `reviewer`, and `client`. At runtime, an `admin`
without a `client_id` becomes a platform admin; an `admin` with a `client_id`
becomes a tenant admin
([`permissions.py:27-35`](../backend/app/core/permissions.py#L27),
[`permissions.py:66-72`](../backend/app/core/permissions.py#L66)). Scope and
actions are centralized rather than repeated route by route
([`permissions.py:37-63`](../backend/app/core/permissions.py#L37)).

| Effective role | Job scope | What the role can do |
| --- | --- | --- |
| Platform admin | Every firm | View, upload, review, export, cancel, and hard-delete jobs; manage all templates, schemas, users, tenants, statistics, and the configured Drive integration. |
| Tenant admin | Its firm | The same job operations for every job in its firm; manage the firm's templates, schema, users, statistics, and Drive/watch configuration. It cannot operate another firm or create/activate/deactivate tenants. |
| Reviewer | Its firm | View, upload, review, and export every job in its firm; use the configured Drive. It cannot manage users, schemas, tenant templates, statistics, or hard-delete another user's job. |
| Normal user (`client`) | Own jobs | Upload, view, review, export, cancel, and delete its own jobs; create its own templates; use Drive if the Drive tenant gate allows it. It cannot see coworkers' jobs merely because they share a firm. |

The exact action sets are at
[`permissions.py:40-59`](../backend/app/core/permissions.py#L40); job scope is at
[`permissions.py:61-63`](../backend/app/core/permissions.py#L61). Template
visibility is owner, same-firm shared, or global default; editing is separately
authorized, so a visible default may still be read-only
([`permissions.py:89-107`](../backend/app/core/permissions.py#L89),
[`templates.py:64-80`](../backend/app/api/routes/templates.py#L64),
[`templates.py:328-340`](../backend/app/api/routes/templates.py#L328)).

Two cautions follow from this design. First, “admin” means two materially
different powers depending only on whether `client_id` is null. Second, a
reviewer can upload and can review every job in the tenant; there is no narrower
read-only or assigned-job reviewer role.

## Cross-user and cross-firm access by guessed id

All job and document endpoints converge on `_get_job_or_404`. A job outside the
caller's scope returns the same 404 as a missing job, while an in-scope job for
which the role lacks the requested action returns 403
([`extract.py:1107-1128`](../backend/app/api/routes/extract.py#L1107)). Document
lookups first scope the job and then require the `doc_id` to belong to that job
([`review.py:52-63`](../backend/app/api/routes/review.py#L52)). This prevents a
valid document id from being paired with a different authorized job id.

The following is the complete persistent path-parameter inventory seen by the
running FastAPI app. “Protected” means user B's request with user A's identifier
matched the missing-id status and normalized body and exposed no marker from A.

| Area | Routes exercised | Result | Source gate |
| --- | --- | --- | --- |
| Tenant state (2) | `POST /api/admin/tenants/{client_id}/deactivate`, `.../activate` | Protected; ordinary users cannot call them and only the platform admin has tenant-wide authority. | [`admin.py:273-284`](../backend/app/api/routes/admin.py#L273) |
| Job reads/downloads (5) | `GET /api/jobs/{job_id}`, `/results`, `/inferred-templates`, `/export`, `/export/zip` | Protected; job scope is checked before data or a workbook/ZIP is built. | [`extract.py:626-908`](../backend/app/api/routes/extract.py#L626) |
| Document edits/review (5) | `PUT .../docs/{doc_id}`, `PATCH .../fields/{ref}`, `PATCH .../rows/{table}/{row}`, `POST .../approve`, `POST .../review` | Protected; both job and document membership are checked. | [`extract.py:969-1038`](../backend/app/api/routes/extract.py#L969), [`review.py:230-293`](../backend/app/api/routes/review.py#L230) |
| Job mutation (2) | `DELETE /api/jobs/{job_id}`, `DELETE /api/jobs/{job_id}/data` | Protected; cancel/delete permissions are checked on the scoped job. | [`extract.py:1040-1087`](../backend/app/api/routes/extract.py#L1040) |
| Review reads/pages (4) | `GET /api/jobs/{job_id}/review`, `/charts`, `.../pages/{page}`, `.../pages/{page}/image` | Protected; all use the same job/document gate. | [`review.py:91-110`](../backend/app/api/routes/review.py#L91), [`review.py:545-630`](../backend/app/api/routes/review.py#L545) |
| Templates (3) | `GET`, `PUT`, `DELETE /api/templates/{template_id}` | Protected; another firm's or another user's private template is 404. A same-firm shared or global default template is readable by design, not a leak. | [`templates.py:64-80`](../backend/app/api/routes/templates.py#L64), [`templates.py:328-340`](../backend/app/api/routes/templates.py#L328) |
| Schemas (2) | `GET`, `DELETE /api/schemas/{client_id}` | Protected; raw YAML is own-tenant/platform only and deletion repeats that scope. | [`schemas.py:143-195`](../backend/app/api/routes/schemas.py#L143) |
| Drive/watch (2) | `GET /api/drive/folders/{folder_id}`, `DELETE /api/watch/{watch_id}` | Protected; Drive is available only to its configured tenant/platform admin, and watch lookup is owner/tenant/platform scoped. | [`drive.py:59-84`](../backend/app/api/routes/drive.py#L59), [`drive.py:316-330`](../backend/app/api/routes/drive.py#L316), [`drive.py:385-400`](../backend/app/api/routes/drive.py#L385) |
| User management (2) | `PUT`, `DELETE /api/admin/users/{user_id}` | Protected; tenant admins' queries add their own `client_id`, platform admins may act globally. | [`admin.py:83-147`](../backend/app/api/routes/admin.py#L83) |

That totals **27 path-id routes, 0 cross-firm leaks**. Source documents do not
have a general raw-download-by-key route; page metadata/images are reached only
through the scoped job/document endpoints, while exports are regenerated from
the scoped result.

Within one firm, the result depends on role and intentional sharing. One normal
user cannot guess a coworker's job id to read, edit, review, export, download
pages from, cancel, or delete that job because normal job scope is `own`. A
reviewer or tenant admin can reach the firm's jobs by design. A normal user may
read a coworker's template only when that template is explicitly same-firm
shared (or global default); a private template is hidden, and a visible shared
template still cannot be edited/deleted by that normal user. These are the
`JOB_SCOPE` and template-view/edit rules cited in the role section, not id-based
exceptions.

Ids carried outside a path were checked too. Upload ignores a body `client_id`
in favor of the caller and scopes `template_id`; flat exports scope both
`job_id` and `template_id`; schema upload cannot name another tenant; Drive
extract/watch are bound to the one configured Drive tenant; user creation is
tenant-scoped; and a tenant admin's usage query ignores another supplied
`client_id`. The inventory guard and those body/query probes are at
[`test_tenant_isolation_all_routes.py:138-147`](../tests/http/test_tenant_isolation_all_routes.py#L138),
[`test_tenant_isolation_all_routes.py:435-511`](../tests/http/test_tenant_isolation_all_routes.py#L435),
and
[`test_tenant_isolation_all_routes.py:516-554`](../tests/http/test_tenant_isolation_all_routes.py#L516).
The three filename-based demo routes resolve only a fixed demo sample whitelist
and are disabled for ordinary tenants
([`test_tenant_isolation_all_routes.py:589`](../tests/http/test_tenant_isolation_all_routes.py#L589)).

This result covers application authorization, not database-operator, host,
bucket-administrator, or backup access. Those remain privileged infrastructure
trust boundaries.

## Authentication

### Password storage and login

New passwords are SHA-256 prehashed and then bcrypt-hashed, avoiding bcrypt's
72-byte truncation limit. Legacy salted SHA-256 hashes are accepted only for
verification and upgraded after a successful login
([`auth.py:27-36`](../backend/app/core/auth.py#L27),
[`auth.py:66-98`](../backend/app/core/auth.py#L66),
[`routes/auth.py:143-151`](../backend/app/api/routes/auth.py#L143)). Login also
runs a dummy bcrypt verification for an unknown username and returns the same
error for an unknown user and a wrong password
([`auth.py:106-111`](../backend/app/core/auth.py#L106),
[`routes/auth.py:117-137`](../backend/app/api/routes/auth.py#L117)).

The login limiter allows five failures per IP-plus-username and locks for 15
minutes. It handles forwarded client IPs according to a configured trusted
proxy count
([`routes/auth.py:30-75`](../backend/app/api/routes/auth.py#L30),
[`routes/auth.py:82-103`](../backend/app/api/routes/auth.py#L82)). It is an
in-process dictionary, so state is lost on restart and is not shared by
multiple backend replicas.

### Token, expiry, logout, and disable

Authentication uses an HS256 JWT Bearer token, not a server session and not an
authentication cookie. The configured lifetime is eight hours
([`auth.py:22`](../backend/app/core/auth.py#L22),
[`auth.py:116-135`](../backend/app/core/auth.py#L116),
[`config.py:58-61`](../backend/app/config.py#L58)). Every authenticated request
reloads an active user row, so deactivating the user makes an otherwise-valid
token fail immediately
([`auth.py:141-167`](../backend/app/core/auth.py#L141)).

Logout is a stateless success response; it does not revoke the JWT
([`routes/auth.py:257-260`](../backend/app/api/routes/auth.py#L257)). Password
changes likewise do not revoke previously issued tokens. The frontend keeps the
Bearer token in local storage, so there are no `Secure`, `HttpOnly`, `SameSite`,
or cookie-expiry settings to audit
([`main.py:482-496`](../backend/app/main.py#L482)). This avoids CSRF-style cookie
authentication but makes XSS protection and explicit token revocation more
important.

### Password reset and bootstrap

There is no self-service forgotten-password/email-token flow. A signed-in user
can use the dedicated change-password route, which proves the current password
and requires a different new password
([`routes/auth.py:236-253`](../backend/app/api/routes/auth.py#L236)). An admin can
set a replacement password and mark it one-time; one-time users are restricted
to profile, password change, and logout until they choose their own password
([`auth.py:38-45`](../backend/app/core/auth.py#L38),
[`admin.py:98-121`](../backend/app/api/routes/admin.py#L98)).

Policy is inconsistent: user/admin creation and `PUT /auth/me` enforce six
characters in current code, while the dedicated change-password schema requires
12. `PUT /auth/me` can replace the password without asking for the current one
again
([`routes/auth.py:203-217`](../backend/app/api/routes/auth.py#L203),
[`admin.py:102-106`](../backend/app/api/routes/admin.py#L102)).

The first platform administrator is created only on an empty database and only
when both explicit bootstrap environment variables are present. Bootstrap
rejects short, username-equal, known-default, and placeholder passwords and
instructs the operator to remove the password variable afterward. There is no
working default account or default credential
([`main.py:292-323`](../backend/app/main.py#L292),
[`main.py:323-384`](../backend/app/main.py#L323)).

## User-management screens

The admin screen lists and filters users, creates them, edits display/email,
role, tenant and status where allowed, and can set a replacement one-time
password
([`admin/page.tsx:78-178`](../frontend/app/admin/page.tsx#L78),
[`admin/page.tsx:250-299`](../frontend/app/admin/page.tsx#L250)). It exposes
Deactivate and Reactivate actions
([`admin/page.tsx:448-480`](../frontend/app/admin/page.tsx#L448)). The API scopes
list/create/update/deactivate to the tenant for tenant admins and to all tenants
for the platform admin
([`admin.py:32-147`](../backend/app/api/routes/admin.py#L32)).

There is no hard-delete-user action: `DELETE /api/admin/users/{id}` is explicitly
a soft deactivation. There is also no self-service recovery screen. The edit
form is the admin password-reset mechanism. The screen labels the minimum as
six characters, reflecting the weaker creation/update rule
([`admin/page.tsx:139-145`](../frontend/app/admin/page.tsx#L139)).

## Audit log: who did what

There is **no general append-only audit log for ordinary customer tenants**.
The database's `DemoActivity` table and its login/upload/export event vocabulary
are deliberately limited to configured demo tenants
([`demo_audit.py:1-16`](../backend/app/core/demo_audit.py#L1),
[`demo_audit.py:45-56`](../backend/app/core/demo_audit.py#L45),
[`models.py:285-324`](../backend/app/models/models.py#L285)). It is not the
accounting firm's audit trail.

Value edits do retain actor, UTC time, target, old value, and new value in an
`edit_log` embedded inside the mutable extraction JSON
([`edits.py:178-213`](../backend/app/services/edits.py#L178),
[`edits.py:238-258`](../backend/app/services/edits.py#L238)). Review marks and
completeness dispositions also store actor/time, and a hard-delete tombstone
stores the actor/time and counts. But ordinary login attempts, reads, downloads,
exports, user/role changes, tenant changes, template/schema changes, and most
administrative actions have no durable customer-visible event stream. The edit
log also has no read endpoint today and is not cryptographically or
database-immutably protected.

## Data deletion and retention

`DELETE /api/jobs/{job_id}/data?confirm=true` is the hard-delete operation. It
is limited to the job owner or an authorized admin, refuses a running job, and
calls one purge implementation
([`extract.py:1063-1087`](../backend/app/api/routes/extract.py#L1063)). The purge:

- removes every source and output object under the tenant/job prefix plus any
  same-tenant legacy source key;
- forgets in-memory page/OCR readings and their temporary copies;
- verifies that stored objects are gone before changing database rows;
- deletes every `DocumentResult`, which removes extracted data, validation,
  review/edit history, and the stored raw model response; and
- clears job paths/messages but retains the job id, owner, tenant, timestamps,
  counts, and a deletion tombstone.

The implementation and verification order are at
[`job_lifecycle.py:30-96`](../backend/app/core/job_lifecycle.py#L30). This is a
complete live-data purge for one job, apart from the intentionally retained
metadata tombstone.

Automatic retention is opt-in and disabled when its day count is zero. It uses
the same purge, one firm at a time, for completed old jobs and runs daily
([`retention.py:1-16`](../backend/app/core/retention.py#L1),
[`retention.py:31-89`](../backend/app/core/retention.py#L31),
[`retention.py:112-123`](../backend/app/core/retention.py#L112)). It is one global
period, not a per-client policy. There is no single whole-firm offboarding purge:
jobs must be purged individually, users are only deactivated, schemas are only
soft-deleted, and the deletion API does not erase backups. Consequently the
answer to “can all of a client's data be deleted completely?” is **not through
one supported workflow**. Live job content can be removed, but tenant metadata,
user rows, schema rows, tombstones, and backup copies need a separate operator
process and declared backup-expiry period.

## File storage and access

Uploads and generated outputs use either local disk or an S3-compatible object
store. Keys are tenant-namespaced as
`clients/{client_id}/jobs/{job_id}/source|output/...`; schemas have their own
tenant key. Key validation rejects traversal, absolute paths, drive letters,
backslashes, empty/dot segments, and tenant ids that would normalize into a
collision
([`storage.py:1-30`](../backend/app/core/storage.py#L1),
[`storage.py:72-104`](../backend/app/core/storage.py#L72),
[`storage.py:135-154`](../backend/app/core/storage.py#L135)). Local paths are
resolved beneath the configured storage root
([`storage.py:439-450`](../backend/app/core/storage.py#L439)).

Application users can read file-derived data only through the scoped job and
document routes described above. There is no route accepting an arbitrary
storage key and no public object URL in the audited API. Infrastructure
operators, the process account, database administrators who can read stored
keys, and the object-store account remain privileged. Local storage is
ephemeral in the documented deployment and can be lost on redeploy; S3/R2 is
the production-shaped choice
([`OPERATIONS.md:12-14`](OPERATIONS.md#L12),
[`OPERATIONS.md:87-88`](OPERATIONS.md#L87)).

The Google Drive integration is one server-wide OAuth credential and is opened
only to the one firm named by `DRIVE_TENANT` (plus the platform admin); an empty
setting closes it for everyone
([`drive.py:59-84`](../backend/app/api/routes/drive.py#L59)). This is safe against
cross-firm browsing as coded, but it is not a per-firm OAuth design.

## Upload limits and file-type checks

The default limits are 50 MB per file, 200 PDF pages, 50 million image pixels,
and 100 files per batch
([`config.py:163-173`](../backend/app/config.py#L163),
[`extract.py:306-307`](../backend/app/api/routes/extract.py#L306)). Content is
validated before a job, storage write, or worker is created. The validator uses
magic bytes rather than trusting the name or MIME type; parses PDFs and rejects
malformed/truncated files and over-page documents; and uses Pillow to verify
PNG, JPEG, and TIFF format, pixel count, decompression-bomb warnings, and
malformation
([`uploads.py:99-143`](../backend/app/services/uploads.py#L99),
[`uploads.py:145-196`](../backend/app/services/uploads.py#L145)). Filenames are
reduced to safe basename/extension forms before storage.

The effective upload allowlist is PDF, PNG, JPEG, and TIFF. The storage layer's
extension vocabulary is broader because it also holds schemas and generated or
internally converted formats; it is not the HTTP upload acceptance rule
([`storage.py:46-51`](../backend/app/core/storage.py#L46)).

## CORS, cookies, and response caching

Development defaults to wildcard CORS and logs a warning. Staging/production
configuration refuses to start with an empty or wildcard origin
([`config.py:130-161`](../backend/app/config.py#L130),
[`config.py:295-357`](../backend/app/config.py#L295)). CORS allows all methods
and headers but sets `allow_credentials=False` because authentication uses a
Bearer header, not cookies
([`main.py:482-497`](../backend/app/main.py#L482)). There are therefore no auth
cookie flags. API responses are also marked not to be stored by shared caches
([`main.py:499`](../backend/app/main.py#L499)).

## Secrets handled by the repository

Only secret locations and uses were inspected; values were not read or printed.
Settings load from process environment and may load a local `.env`, while
validation is configured to hide input values from errors
([`config.py:38-48`](../backend/app/config.py#L38)). The secret-bearing settings
and consumers are:

| Secret/configuration class | Where it is consumed |
| --- | --- |
| JWT signing secret and algorithm | Token creation/verification in [`auth.py:116-135`](../backend/app/core/auth.py#L116). Production rejects a short or placeholder signing secret in [`config.py:319-323`](../backend/app/config.py#L319). |
| Database connection URL | SQLAlchemy engine creation in [`models.py:329-350`](../backend/app/models/models.py#L329). |
| Model-provider API credential | Provider client construction in [`gemini_client.py:132`](../backend/engine/connectors/gemini_client.py#L132). |
| S3/R2 access credentials, endpoint, and bucket | Object-store client construction in [`storage.py:453-463`](../backend/app/core/storage.py#L453). |
| Google Drive OAuth client/token material | The Drive connector is loaded by [`drive.py:87-107`](../backend/app/api/routes/drive.py#L87), and access is tenant-gated before use. |
| Bootstrap administrator username/password | Read from explicit process environment variables only in [`main.py:292-342`](../backend/app/main.py#L292). |
| Redis/Celery connection URLs | Declared for worker/broker use in [`config.py:125-128`](../backend/app/config.py#L125). |

Production validation requires an explicit database, required object-store
credentials when S3 is selected, a provider key for the selected provider, an
explicit CORS origin, and a non-placeholder signing secret; it also refuses the
stub provider outside development
([`config.py:295-365`](../backend/app/config.py#L295)). Repository history and
deployed secret-manager configuration were outside this filesystem-only audit.

## Document contents and personal data in logs

The stated logging policy permits ids, counts, statuses, exception class names,
and timings, but forbids document text, extracted values, client filenames,
prompts, and model answers
([`log_safety.py:1-7`](../backend/engine/log_safety.py#L1)). Safe traceback output
omits exception messages, and document-reading libraries are capped at warning
to prevent verbose page text from reaching logs
([`log_safety.py:104-140`](../backend/engine/log_safety.py#L104)). The access log
records method and path only, never the query string, specifically because a
query may carry a token or document name
([`observability.py:1-15`](../backend/app/core/observability.py#L1),
[`observability.py:84`](../backend/app/core/observability.py#L84)).

Offline sentinel tests exercise success and failure paths and reject content in
captured logs
([`test_logs_carry_no_content.py:1`](../tests/http/test_logs_carry_no_content.py#L1),
[`test_logs_carry_no_content.py:189`](../tests/http/test_logs_carry_no_content.py#L189),
[`test_export_logs_carry_no_content.py:1`](../tests/test_export_logs_carry_no_content.py#L1)).
This is strong evidence that SSNs and account numbers present as document
content are not intentionally logged. It is not a formal DLP scanner: there is
no special SSN/account-number redactor that could rescue a future unsafe log
statement. The database does retain full extraction JSON and an exact raw model
response for each document
([`models.py:125-166`](../backend/app/models/models.py#L125)).

## Backups

The repository documents a plan, not evidence that the deployed backups exist.
It says the operator must verify whether Railway Postgres backups are enabled,
their schedule, and retention; independently take encrypted database dumps;
create a separate R2 copy because object versioning is intentionally off; and
test a restore quarterly. It also explicitly notes that backups retain deleted
data until they expire
([`OPERATIONS.md:95-108`](OPERATIONS.md#L95)).

Therefore backup availability, encryption, schedule, access control, geographic
location, retention, and restore success are **unverified deployment controls**
in this audit. R2 has no backup unless the operator has created the documented
second copy.

## Ten gaps most likely to block a first paying accounting-firm client

Ranked by likelihood of blocking a security/procurement review, with the
smallest credible change rather than a full redesign:

| Rank | Gap | Why it blocks | Smallest change |
| ---: | --- | --- | --- |
| 1 | No ordinary-tenant audit log | The firm cannot prove who signed in, viewed, exported, edited, approved, deleted, or changed access. | Add an append-only `audit_events` table and record auth, read/download/export, edit/review, delete, and admin changes with tenant, actor, target, time, outcome, and request id, never document content. |
| 2 | No MFA or enterprise SSO | Password-only administrator access is commonly rejected for financial data. | Add TOTP for platform and tenant admins first, with recovery codes; or integrate one OIDC provider and enforce it per tenant. |
| 3 | No verified backup/restore control | The repo cannot demonstrate recoverability, and object storage may have no second copy. | Turn on scheduled encrypted DB backups and a second-bucket object copy, document retention/access, and attach evidence from one staging restore. |
| 4 | Retention/offboarding is not client-specific or complete | Retention is globally configured/off by default, and no workflow erases a whole tenant plus declares backup expiry. | Store a retention period per tenant and add an operator-only firm purge/report that covers jobs, schemas, users, objects, tombstone policy, and the date backup copies expire. |
| 5 | Logout/password change cannot revoke JWTs | A copied token remains usable for up to eight hours unless the user is deactivated. | Add a user `token_version` claim checked on every request and increment it on logout-all/password reset; shorten access-token life if practical. |
| 6 | Password policy and recovery paths disagree | Six-character create/profile/admin-reset paths undercut the 12-character change-password rule; there is no safe forgotten-password flow. | Apply one 12+ validation schema everywhere, require current-password proof for self-service changes, and add a short-lived one-use reset token or retain admin one-time reset with audit events. |
| 7 | Brute-force state is process-local | Restarting or adding replicas resets/splits the five-attempt counter. | Move the same IP-plus-username window to Redis and emit an audit/security alert on lockout. |
| 8 | Platform admin is implicit and all-powerful | A null `client_id` silently turns stored `admin` into cross-tenant access, making role review and least privilege harder. | Migrate to an explicit `platform_admin` role, reject null-tenant ordinary admins, and require a separate operator account for cross-tenant support. |
| 9 | Raw model responses and vendor handling lack a minimum-retention control | The database intentionally keeps an exact provider response that may duplicate SSNs/account numbers; procurement will ask about provider use, region, training, and deletion. | Stop retaining raw responses by default, add a short diagnostic TTL/tenant opt-in, and document the provider DPA, region, no-training setting, and deletion behavior. |
| 10 | Google Drive is one server-wide credential | Only one configured firm can safely use Drive; it is not scalable or administratively isolated per paying tenant. | Hide Drive for all other tenants now, then store a separately encrypted OAuth grant keyed by tenant and make every Drive lookup select that tenant's grant. |

Tenant isolation itself did not enter the ranked gaps because the tested API
surface currently passed: **0/27 persistent id routes leaked**. That result
should remain a release gate through the route-inventory test.
