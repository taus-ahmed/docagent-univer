# Onboarding a client firm

For the person who brings a new accounting firm onto DocAgent. Every firm is
fully separate: its users, documents, results, templates and usage are visible
only inside that firm ([SECURITY.md, "Isolation between firms"](SECURITY.md)).

Words used here: a **firm** is a client company (internally its `client_id`,
for example `smith_cpa`). The **platform admin** is you — the one account with
no firm, which can create firms. A firm's **admin** manages that firm's users.

## 1. Create the firm and its first admin

Either way gives a **one-time password**, shown once.

**From the app (recommended).** Sign in as the platform admin and call
`POST /api/admin/tenants` with:

```json
{"client_id": "smith_cpa", "client_name": "Smith & Partners CPA",
 "admin_username": "smith_admin", "admin_display_name": "Jane Smith"}
```

The firm id may use letters, digits, `.`, `_` and `-`, and must start and end
with a letter or digit. It is permanent: it names the firm's storage folder.

**From a terminal** (with `DATABASE_URL` set to the database you mean):

```
python scripts/create_tenant.py --firm-id smith_cpa --firm-name "Smith & Partners CPA" \
    --admin-username smith_admin --confirm-database remote
```

`--confirm-database` must say whether that database is `local` or `remote`;
the script refuses otherwise and never prints the database address. It prints
the one-time password once and stores it nowhere readable.

Both create the firm's extraction schema from the standard accounting schema.
A firm with special document types can be given its own YAML later
(`POST /api/schemas`, platform admin or the firm's admin).

## 2. Give the temporary password safely

- Send the **username and the password by different channels** (for example
  the username by email, the password by phone or a password manager share).
- Never put the password in a ticket, chat channel or shared document.
- It is one-time: until it is changed the account can do nothing but change
  it, so a password intercepted after first use is worthless.

## 3. First sign-in

The admin signs in with the one-time password and is asked to choose their own
(at least 12 characters). Nothing else opens until they do.

## 4. The firm's admin adds their people

In **Admin → Users**, the firm admin creates accounts in their own firm only:

| Role | Can |
|---|---|
| Administrator | everything in the firm: users, templates, schemas, statistics, usage, delete any job |
| Reviewer | see, check, edit and export every job in the firm; no users, templates or schemas |
| User | upload, see and export **their own** jobs; delete their own jobs |

Leave "must change password at first sign-in" ticked, and hand over each
temporary password as in step 2.

## 5. A first document

A user opens **Extract**, optionally picks a template, drops a PDF or image and
starts. The results grid shows each value with its status: verbatim from the
document, unverified (from a scan), low confidence, or edited. The review
screen shows each value on the page it came from. Values that need a look are
marked in the export too, and the export never hides them as final.

## 6. What the client sees

Only their own firm: their jobs (or, for a user, their own jobs), their
templates and the shared system templates, their usage. Another firm's job or
template id answers "not found", exactly like an id that does not exist.

## 7. Cost control

`TENANT_MONTHLY_PAGE_LIMIT` caps pages per firm per calendar month (0 =
unlimited). A firm can have its own limit: add `monthly_page_limit: 500` to its
schema YAML. Over the limit, an upload is refused with a message giving the
counts and the reset date; nothing is processed. A firm admin sees usage at
`GET /api/usage` and on the Admin page; the platform admin sees every firm at
`GET /api/admin/tenants`.

## 8. When someone leaves

The firm admin deactivates the user (**Admin → Users**, deactivate). They can
no longer sign in, and every token they hold stops working at once. Their jobs
stay with the firm.

## 9. Offboarding a firm

1. **Deactivate:** `POST /api/admin/tenants/{client_id}/deactivate` (platform
   admin). Every user of the firm is deactivated; data is kept.
   `.../activate` undoes it.
2. **Export first, if the firm wants its data:** each job's workbook is
   `GET /api/jobs/{id}/export` (or `/export/zip` per file).
3. **Delete:** every job's files and results go with
   `DELETE /api/jobs/{id}/data?confirm=true` (the firm admin or platform
   admin; the job's own user for their own jobs). The job record stays as an
   empty, marked-deleted row. Deleting a whole firm in one step, its schema and
   its user rows needs the retention v2 work
   ([proposals/retention-v2.md](proposals/retention-v2.md)).
4. With `DATA_RETENTION_DAYS` set, old jobs are deleted automatically each day
   ([OPERATIONS.md](OPERATIONS.md)).
5. Backups keep deleted data until they expire — see
   [CLIENT-DATA-FAQ.md](CLIENT-DATA-FAQ.md).
