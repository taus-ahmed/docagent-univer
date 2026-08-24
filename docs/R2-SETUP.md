# Cloudflare R2 setup — console work, then five variables

Written 2026-08-24 at `836ea68`. Everything here is **yours to do in the
Cloudflare and Railway dashboards**; the code side is already done and
deployed-ready.

Read `docs/DEPLOY-RUNBOOK.md` §1.2 first for what the storage abstraction
actually is. The short version: a file is identified by a key, the key is the
same string on both backends, and `STORAGE_BACKEND` picks which one holds it.
**No route changes, no migration, no code branch to enable.**

You do not have to do this to deploy Phase 9 — `STORAGE_BACKEND=local` is what
production runs today and the deploy is safe either way. Do it when you want
uploads to survive a redeploy.

---

## 1. Create the bucket

Cloudflare dashboard → **R2** → **Create bucket**.

| field | value | why |
|---|---|---|
| Name | `docagent-prod` | Used verbatim as `S3_BUCKET`. Lowercase, hyphens; no dots — a dot in a bucket name breaks TLS hostname matching on some S3 clients |
| Location | **Automatic**, or the hint nearest `us-east4` | The backend runs in Railway's `us-east4-eqdc4a`. Every read is server-side from that region |
| Storage class | Standard | Infrequent Access has a 30-day minimum duration charge; source PDFs are read within minutes of upload |

**Leave public access DISABLED.** Do not connect a custom domain, and do not
enable `r2.dev` public access. Every object in this bucket is a customer
document. The application never needs the bucket to be public: reads go through
the backend, and `signed_url()` mints a time-limited URL (capped at 1 hour, and
returning `None` on the local backend so a never-expiring link cannot ship by
accident).

**Object lifecycle rules: none for now.** Phase 11 adds retention, and it does
it in the application (`delete_job_sources()` removes a job's sources and
leaves its outputs) because "delete the document, keep the extracted values" is
a product rule, not an age rule. A lifecycle rule that expires everything under
a prefix would delete outputs too.

**Note the Account ID** from the R2 overview page — the 32-character hex string.
You need it for the endpoint URL in §3.

---

## 2. Create the API token

Cloudflare dashboard → **R2** → **Manage R2 API Tokens** → **Create API token**.

| field | value |
|---|---|
| Token name | `docagent-backend-prod` |
| Permission | **Object Read & Write** |
| Specify bucket(s) | **Apply to specific buckets only** → `docagent-prod` |
| TTL | Forever (or set a rotation date and diarise it) |
| Client IP filtering | Leave empty — Railway egress IPs are not stable |

**Scope it to the one bucket.** "Apply to all buckets" is the default and it is
the wrong choice: this credential lives in a Railway environment variable, and
a leak should cost you one bucket, not the account's object storage.

**Object Read & Write is the minimum that works**, not a convenience choice.
The code calls exactly these operations (`backend/app/core/storage.py`):

| operation | where |
|---|---|
| `PutObject` | uploads, generated outputs, schema materialisation |
| `GetObject` | the worker fetching a source document; presigned URLs |
| `HeadObject` | `exists()`, used by `_materialise_schemas` to stay idempotent |
| `DeleteObject`, `DeleteObjects` | Phase 11 retention |
| `ListObjectsV2` | `delete_prefix()`, paginated |

Admin Read & Write additionally grants bucket creation and deletion. The
application never creates or deletes a bucket, so that permission only adds
blast radius.

On the confirmation screen Cloudflare shows the values **once**:

- **Access Key ID** → `AWS_ACCESS_KEY_ID`
- **Secret Access Key** → `AWS_SECRET_ACCESS_KEY`
- the S3 API endpoint, `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`

Copy all three now. The secret is not shown again.

---

## 3. Set the variables — backend service only

Railway → project `resilient-youthfulness` → **`docagent-univer`** →
**Variables**.

| variable | value | notes |
|---|---|---|
| `STORAGE_BACKEND` | `s3` | The switch. Anything other than `s3` means local |
| `S3_BUCKET` | `docagent-prod` | Exactly the bucket name from §1 |
| `S3_ENDPOINT_URL` | `https://<ACCOUNT_ID>.r2.cloudflarestorage.com` | **No bucket name in the path.** boto3 appends it. A trailing slash is fine; a path suffix is not |
| `AWS_ACCESS_KEY_ID` | from §2 | |
| `AWS_SECRET_ACCESS_KEY` | from §2 | |
| `AWS_REGION` | `auto` | R2's only region token. `us-east-1` (the code default) usually works because R2 is lenient about SigV4 region, but `auto` is what Cloudflare documents — set it explicitly rather than relying on tolerance |

**These go on `docagent-univer` and nowhere else.**

- **`loving-grace` (frontend): no.** It never touches storage — it talks to the
  backend API and nothing else. Grepping the whole frontend for `S3_`, `AWS_`,
  `STORAGE_BACKEND` or `cloudflarestorage` returns nothing. Putting an R2
  secret on a Next.js service is how a secret ends up in a client bundle.
- **`Postgres`: no.**

Setting variables triggers a redeploy of that service. That is expected and is
the point at which the backend starts using R2.

---

## 4. Verify

After the backend redeploys:

- [ ] **The variables are actually set.**
  ```bash
  railway variables --service docagent-univer --kv | grep -E '^(STORAGE_BACKEND|S3_|AWS_REGION)'
  ```
  **Expect:** `STORAGE_BACKEND=s3`, the bucket, the endpoint, `AWS_REGION=auto`.
  (The two credentials are secret; confirm they exist by name.)

- [ ] **The service booted.**
  ```bash
  railway logs --service docagent-univer | head -40
  curl -s https://docagent-univer-production.up.railway.app/health
  ```
  **Expect:** the boot sequence in the runbook §5.3b, and
  `{"status":"ok","version":"2.0.0","env":"production"}`.
  A bad endpoint or a wrong key does **not** stop boot — the S3 client is built
  lazily on first use. The failure surfaces at step 3 below, not here.

- [ ] **The schema reached the bucket.** This is the sharpest single check,
      because `_materialise_schemas` writes through the same storage layer at
      every boot: if the credentials work, the object exists.

  Cloudflare dashboard → R2 → `docagent-prod` → **Objects**.
  **Expect:** `schemas/clients/demo_001.yaml`, about 7.4 KB.

  If it is missing, the boot log will have
  `Could not materialise schema for demo_001: …` with the underlying error —
  `SignatureDoesNotMatch` (wrong secret), `NoSuchBucket` (wrong name or the
  bucket name is in the endpoint path), or a DNS failure (malformed endpoint).

- [ ] **An upload round-trips.** Upload one PDF through the UI.
  **Expect:** the job reaches `completed`, and the bucket now holds
  `clients/<client_id>/jobs/<job_id>/source/<filename>.pdf`.

  A job that reaches **`failed`** with every document saying *"Source document
  is no longer in storage — upload it again to re-run this job."* means the
  write succeeded but the read did not, which points at a token scoped to the
  wrong bucket. A job that fails at upload time with a 500 means the write
  itself failed — `StorageError` is deliberately fatal, because a write that
  silently did nothing would leave a job pointing at an empty key.

- [ ] **Redeploy and confirm the source survived.** The whole point.
      Trigger a redeploy, then re-download the export from the job above and
      confirm the object is still listed in the bucket.
      **Expect:** both work. On `local` the object would have died with the
      container.

---

## 5. Things worth knowing before you turn it on

**Historical documents do not come back.** The 222 existing document results
have no source file anywhere — nothing was ever copied. `s3_key` stays NULL for
them, which now means exactly one thing: no source is retained. See runbook §3.

**Do not bump boto3 casually.** `requirements.txt` pins `boto3==1.34.144`.
Releases from 1.36 onward send additional integrity checksums by default, which
S3-compatible stores have historically rejected. If you upgrade, re-run the §4
verification rather than assuming.

**Existing local files are not migrated, and do not need to be.** There are
none worth moving (§3), exports are rebuilt from the database on every
download, and schemas re-materialise at boot. Switching the variable is the
whole migration.

**The key layout is tenancy-ready but not tenancy-enforced.** Every
tenant-owned key starts `clients/{client_id}/`, so a future scoped credential
or an IAM prefix condition can enforce at the bucket what the code enforces
today. Nothing enforces it at the bucket right now — one token reads and writes
the whole bucket.

**Bucket CORS is not needed today** and should not be added speculatively.
`signed_url()` exists and is tested but is not wired to any route, so no
browser ever talks to R2 directly. If Phase 11 wires it, that is the moment to
add a CORS rule scoped to the frontend origin.

**Rolling back to `local`** is one variable. Objects already in R2 stay there
and cost nothing meaningful; nothing on the local backend reads them. Do not
delete the bucket on a rollback — you will want those objects when you roll
forward.

---

## 6. Cost, roughly

R2 charges for storage and operations, and **not for egress**, which is the
reason to prefer it here over S3.

At the current production volume — 222 documents over three months, average
source PDF well under 1 MB — storage is under 1 GB and the whole bill rounds to
the free tier (10 GB storage, 1 M Class A ops, 10 M Class B ops per month).
Each extraction is a handful of operations: one `PutObject` per upload, one
`GetObject` in the worker, one `HeadObject` per schema check at boot.

The number that would change this is retention: if Phase 11 keeps sources
indefinitely at a much higher volume, storage grows linearly. That is an
argument for implementing retention, not for a different store.
