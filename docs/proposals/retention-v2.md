# Retention v2 — per-firm periods, firm deletion, an audit trail

Proposal only (round 14). Needs a migration, so it is **not** built; round 14
shipped what needs none ([../OPERATIONS.md](../OPERATIONS.md) §2,
`app/core/retention.py`): one global `DATA_RETENTION_DAYS`, a daily purge firm
by firm, owner and admin hard delete with `?confirm=true`.

## What is missing, and why it needs schema

| Need | Why a column or table |
|---|---|
| A retention period **per firm** | there is no firm table; the firm's YAML could hold it (as `monthly_page_limit` does) but a period is a contract term that must not be editable by the firm's own admin through a schema upload |
| **Delete a whole firm** (users, schema, templates, watch folders, every job) | users are referenced by jobs and templates; deleting them needs a "deleted firm" state to keep the job tombstones meaningful |
| An **audit trail** (who uploaded, viewed, exported, edited, deleted) | append-only rows with no document content, kept ~2 years; logs are not a record (provider retention ⚠ VERIFY) |
| A `purged` status | today a deleted job is a mark in `notes`; queries for "live" jobs parse JSON |

## Design

1. **Migration (additive, idempotent, nullable):** table `tenants(client_id PK,
   name, retention_days NULL, page_limit NULL, deactivated_at NULL,
   deleted_at NULL)` backfilled from distinct `client_id`s at first boot
   (insert-if-missing; no existing row rewritten); table `audit_events(id,
   at, user_id, client_id, action, job_id NULL, detail_json)` with an index on
   `(client_id, at)`. Rollback: drop both tables; nothing else references them.
2. `retention.purge_expired` reads `tenants.retention_days` (NULL → global).
3. `DELETE /api/admin/tenants/{id}?confirm=<client_id>` (platform admin, typed
   confirmation): purge every job through `purge_job`, delete templates,
   watch folders, the schema row and file; users deactivated and anonymised
   (username → `deleted-<id>`), the `tenants` row kept with `deleted_at`.
4. Audit writes in the same places `demo_audit` writes today, for every firm.
5. Move the page limit from the YAML into `tenants.page_limit`.

**Needs staging verification before main**: the live demo database runs
startup migrations on deploy.

## Decisions for Tauseef

1. The default period (90 days was proposed) and min/max.
2. Whether a firm admin may shorten (never lengthen) their firm's period.
3. Keep or stop storing the raw model answer (`raw_llm_response`).
4. What to promise about backups holding deleted data.
