# Security notes

What the code does today, and the gaps that are known and open. Each statement
names the code that implements it.

## Authentication

- **JWT, HS256, stateless** (`app/core/auth.py`). The payload is
  `{sub: user id, role, client_id}`. Logout is a server no-op; the token expiry
  (`ACCESS_TOKEN_EXPIRE_MINUTES`) is the only invalidation.
- **`SECRET_KEY`**: a production boot refuses every shipped placeholder
  (`config.py::_PLACEHOLDER_SECRETS`,
  `_refuse_to_run_production_on_a_known_key`). Generate one with
  `openssl rand -hex 32`.
- **First administrator**: there is no default account. One is created at boot
  only from `DOCAGENT_BOOTSTRAP_ADMIN_USERNAME` / `_PASSWORD` when no
  administrator exists; known default passwords are refused
  (`main.py::_bootstrap_admin`). Remove the password variable after the first boot.
- **Login rate limit**: 5 failed attempts per IP locks that IP out for 15
  minutes (`routes/auth.py`). It is in memory, so it resets on restart and does
  not span instances. `X-Forwarded-For` is trusted (Railway's proxy).

## Tenancy

- Every data table carries `client_id`. The tenant a request acts as comes from
  the **token, never the request body** (`extract.py::resolve_client_id`); a
  super-administrator (role `admin`, no `client_id`) must name the client.
- Jobs: `_get_job_or_404` allows a super-administrator, an administrator or
  `company_admin` of the job's tenant, or the job's own user.
- Templates: `load_template_for_user` checks ownership before an upload uses a
  template id; an unknown id fails rather than silently extracting without one.

## Uploads and storage

- Limits: `MAX_UPLOAD_SIZE_MB` (alias `MAX_FILE_SIZE_MB`), `MAX_PDF_PAGES`,
  `MAX_IMAGE_PIXELS`, `MAX_FILES_PER_BATCH`; invalid values fall back to safe
  defaults.
- Storage keys are built in one place and validated by `storage._safe_key`
  (no `..`, absolute paths, drive letters, backslashes or empty segments); the
  local backend re-checks that the resolved path stays under the storage root.
  `client_id` leads every tenant-owned key.
- Exports are rebuilt from the stored result on every download, never stored.

## Secrets

- `.env` files are ignored by git. `backend/.env.example` lists every variable
  with placeholder values only.
- The model provider key (`GEMINI_API_KEY`) is read from the environment and
  sent only to the provider's API.
- ⚠ An old commit on `main` (`ecaead9`, 2026-04-26) contains a Groq API key in
  `.env.example`. It was replaced in the next change but remains in history;
  the key must be treated as compromised and revoked at the provider.

## Known gaps

| Gap | Where | Note |
|---|---|---|
| Passwords are one round of salted SHA-256 | `auth.py::hash_password` | needs a KDF (bcrypt / scrypt / argon2) and a rehash-on-login migration |
| A password change does not invalidate issued tokens | `auth.py` | needs a token version or deny list |
| Rate limiter is per process | `routes/auth.py` | needs a shared store before running more than one instance |
| `company_admin` exists in RBAC but `UserCreate` cannot assign it | `schemas.py` | the role matrix is not documented in one place |
| Job access answers 403 for another tenant's job | `_get_job_or_404` | reveals that the id exists |
