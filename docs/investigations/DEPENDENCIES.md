# Dependency hygiene (2026-10-23; Run 15 triage 2026-10-26)

## Run 15: npm audit and pip-audit, triaged

### Frontend (`npm audit`, 2026-10-26)

Before: 15 advisories (1 critical, 11 high, 3 moderate). `npm audit fix`
(**no `--force`**: only upgrades inside the ranges `package.json` already
allows) changed `package-lock.json` only, and fixed 7 of them: `axios`
1.14.0 → 1.20.0 (SSRF via NO_PROXY, prototype-pollution auth bypass — **production**:
the browser app's API client), `form-data`, `follow-redirects` (axios's, production),
`brace-expansion`, `browserslist`, `baseline-browser-mapping`, `js-yaml`,
`nanoid`, `source-map-js` (build tooling). After: type-check clean, 21/21
frontend tests, production build OK.

Left: 8 (1 critical, 4 high, 3 moderate), none fixable inside the current
major versions:

| Package | Where it runs | Advisories (summary) | Why not fixed |
|---|---|---|---|
| `next` 14.2.35 | **production** (the frontend server: Vercel, or `Dockerfile.frontend`) | 25, the latest 14.2 has them all. What applies to this app: React Server Components DoS (App Router — the app uses it), cache-confusion / cache-poisoning of RSC responses, `/_next/image` optimizer DoS and RCE-with-SVG/AVIF (the endpoint exists by default; the app uses no `next/image`, no `remotePatterns`, so only local `/public` images reach it). **Do not apply:** Server Actions (none), `rewrites` (none), middleware/i18n (none), Windows-hosted RCE (Linux), WebSocket upgrades, CSP nonces, `beforeInteractive` | fixed only in **15.5.28+ / 16.x** — a major upgrade (Next 15 App Router needs React 19). **Proposal:** upgrade Next and React together on a branch, with the frontend tests, a build and a staging pass; meanwhile `images: { unoptimized: true }` in `next.config.js` would close the optimizer advisories at no cost to this app (no `next/image`) — not done here, it changes production behaviour without a staging check |
| `postcss` (bundled inside `next`) | build time | 4 (sourceMappingURL file read, `</style>` XSS in stringify) | ships inside `next`; goes with the Next upgrade. Reachable only when building attacker-supplied CSS — the build compiles this repo's own CSS |
| `eslint-config-next`, `@next/eslint-plugin-next`, `glob` | **dev only** (lint) | glob CLI `-c` command injection | the glob CLI is never invoked; fixed only with the Next 16 line |
| `tailwindcss` 3.4.19, `postcss-nested`, `postcss-selector-parser` | build time | selector-parser quadratic CPU | 3.4.19 is the newest 3.x; Tailwind 4 is a rewrite. Reachable only with attacker-supplied CSS at build |

### Python (`pip-audit 2.10.1`, 2026-10-26)

Run from a throwaway virtualenv in the scratchpad over the 97 pins in
`backend/constraints.txt` (read-only advisory queries; the S1 venv, which
belongs to another worktree, was not touched). 46 advisory rows in 9 packages
(duplicates across PYSEC/GHSA ids collapsed below).

| Package | Pinned | Where it runs | Decision |
|---|---|---|---|
| python-multipart | 0.0.9 → **0.0.31** | **production**: parses every upload (form-data CRLF, header DoS, Content-Length, querystring `;`) | **upgraded** — FastAPI 0.111 requires `>=0.0.7`, so in range |
| pypdf | 6.21.1 → **6.21.2** | **production**: page counts and AcroForm widgets of uploads (crafted-PDF long runtime ×3) | **upgraded** (patch); native readings identical 69/69 |
| python-jose[cryptography] | 3.3.0 → **3.5.0** | **production**: signs and verifies every JWT (HS256) | **upgraded**; fixes the algorithm-confusion and JWE-decrypt DoS advisories. PYSEC-2026-4298 (asymmetric key in HMAC init) has **no fixed release**; it needs an attacker-chosen key, and the app's key is its own `SECRET_KEY` — replacing python-jose with PyJWT is the lasting fix (proposal) |
| python-dotenv | 1.0.1 → **1.2.2** | production (reads `.env` at boot; the advisory is in `set_key`, which the app never calls) | **upgraded** |
| starlette | 0.37.2 | **production** (every request: multipart, Host header, path) | **not changed**: fixes need Starlette ≥0.40 … 1.3.1, and FastAPI 0.111 pins `<0.38`. Needs a FastAPI upgrade, its own change with the full gate |
| ecdsa | 0.19.2 | via python-jose; HS256 never uses it | no fixed release; goes away with PyJWT |
| protobuf | 4.25.9 | via `google-api-python-client` (Drive); the DoS is in `json_format.ParseDict`, which the app does not call | not changed (5.x is a major for the Google clients) |
| pillow-heif | 0.16.0 | HEIF uploads only | not changed: 1.x is a major, and it sits beside Pillow (replay rule) |
| pytest | 8.2.2 | **dev only**; advisory is the UNIX `/tmp/pytest-of-user` directory | not changed (9.x is a major) |

**Verification of the four upgrades** (they change what production installs):
a fresh throwaway virtualenv (CPython 3.11.16, Windows) with the upgraded
`constraints.txt` installed `--no-deps` (minus `uvloop`, Linux-only), `pip
check` clean; in a clean `git archive` export, `OCR_WORKERS=1`: full suite —
the only failures were two tests whose stubs had the pre-item-9 signature
(fixed, 6e79c75, a bug in this run, not in the upgrades); native readings
**69/69 identical**; harness **97.2% templated / 96.7% no-template**, both
unchanged. Pillow, Poppler and pdfplumber/pdfminer were not touched. **The
Linux production image was not built here (no Docker): build it and run the
smoke check before deploy.** The S1 venv (another worktree's) still has the
old four versions; the gate ran there too.

Remaining work, in order: FastAPI + Starlette (production request parsing);
PyJWT in place of python-jose (removes ecdsa); Next 15/16 + React 19 (frontend);
then the majors (protobuf, pillow-heif with Pillow, pytest).

## Round 12: what changed

| Package | Change | Evidence |
|---|---|---|
| `bcrypt==5.0.0` | **now named** in `requirements.txt` (it arrived through `passlib[bcrypt]`) | `app/core/auth.py` imports `bcrypt` directly; same version as the old constraint |
| `passlib[bcrypt]` | **removed** | no import in `backend/`, `tests/` or any script; only a comment named it |
| `google-generativeai` | **removed**, with `google-ai-generativelanguage`, `grpcio`, `grpcio-status`, `tqdm` | no import; the client is pure `urllib` (`gemini_client.py:10`). A fresh install without it no longer pulls those four; `google-api-core`, `protobuf`, `proto-plus` stay (needed by `google-api-python-client`) |
| `aiofiles` | **removed** | no import |
| `rich==15.0.0` | **now named** | `engine/orchestrator.py` imports it at module level and the API imports `Orchestrator`; same version as the old constraint |
| `Pillow` | **10.4.0 → 13.0.0** (48 advisories) | page images and OCR text byte-identical on the corpus, 0 cache misses, suite and harness unchanged (`proposals/replay-portability.md`); `Image.getdata` deprecated, `engine/ocr_source.py:179` |

`constraints.txt`: the seven packages a fresh install no longer pulls were
removed; nothing else moved. Verified with a fresh virtualenv on this machine
(Windows, CPython 3.11.16): `pip install -r requirements.txt -r
requirements-dev.txt -c constraints.txt`, `pip check` clean, every module
under `backend/app` and `backend/engine` imports (65/65, same as the S1
venv), and the full suite plus both harness modes from that venv (Round 12
log in PROGRESS). **The Linux production image (`Dockerfile.backend`) was not
built here (no Docker); it needs its own build and smoke check before deploy.**

`httpx` stays in `requirements.txt` (test-only, moving it is a separate,
behaviour-free change).

## Round 11 report (unchanged below)

Every item that touches `backend/requirements.txt` changes what production
installs, so each is a proposal for a reviewed commit with a production image
build (`Dockerfile.backend`) and the full gate.

## Unused or indirect dependencies (backend)

Evidence is a search of `backend/` and `tests/` for each module's import name.

| Package | Status | Evidence | Proposal |
|---|---|---|---|
| `google-generativeai==0.7.2` | **unused** | no import anywhere; `engine/connectors/gemini_client.py:10` says "No google-generativeai SDK dependency — pure urllib". It pulls `google-ai-generativelanguage`, `grpcio`, `grpcio-status`, `protobuf` (one advisory, below) into the image | remove; drop the four transitive pins from `constraints.txt` once nothing else needs them (`google-api-python-client` needs `google-api-core`, not grpc) |
| `rich` | **used, only installed indirectly** | `engine/orchestrator.py:17–20` imports it at module level, and the API imports `Orchestrator`; it arrives only through FastAPI's CLI extras (`rich==15.0.0` in `constraints.txt`) | add `rich` to `requirements.txt` explicitly at the pinned version, or move the `rich` imports inside the CLI code paths |
| `passlib[bcrypt]==1.7.4` | **unused since a906ce2** | `app/core/auth.py` calls `bcrypt` directly; passlib is unmaintained and warns with bcrypt ≥ 4.1 | replace with `bcrypt==5.0.0` (the version already installed) |
| `aiofiles==23.2.1` | **unused** | no import | remove |
| `httpx==0.27.0` | **test-only** | no import in `backend/`; Starlette's `TestClient` needs it | move to `requirements-dev.txt` |
| `python-multipart`, `psycopg2-binary` | used implicitly | FastAPI form/upload parsing; SQLAlchemy's PostgreSQL driver | keep |
| `pdfminer.six` | pinned on purpose | pdfplumber's engine, pinned because text extraction output is part of every cache key | keep |

No duplicate pins: `requirements.txt` and `constraints.txt` agree on every
package both name.

## Known vulnerabilities (Python) — Round 11, superseded by Run 15 above

`pip-audit 2.10.1` (PyPI advisory service, read-only queries) over the 97 pins
in `backend/constraints.txt`, run from a throwaway virtualenv in the scratchpad
(the project venv was not touched). Unique advisory ids per package:

| Package | Pinned | Advisories | Fixed in (highest listed) | Note |
|---|---|---|---|---|
| pillow | 10.4.0 | 48 | 13.0.0 | **image parsing of uploads**. ⚠ Upgrading changes how page images are encoded, which invalidates every replay key (docs/proposals/replay-portability.md) — plan the upgrade together with the cache |
| python-multipart | 0.0.9 | 7 | 0.0.31 | multipart parsing of every upload; tied to the FastAPI/Starlette versions |
| starlette | 0.37.2 | 7 | 1.3.1 | via FastAPI 0.111; needs a FastAPI upgrade |
| python-jose | 3.3.0 | 4 | 3.4.0 (two have no fix) | JWT signing/verification; consider PyJWT |
| pypdf | 6.21.1 | 3 | 6.21.2 | patch release; PDF parsing of uploads |
| ecdsa | 0.19.2 | 1 | none published | via python-jose; HS256 does not use it |
| pillow-heif | 0.16.0 | 1 | 1.3.0 | |
| protobuf | 4.25.9 | 1 | 6.33.5 | only via the unused `google-generativeai` — removing that removes it |
| python-dotenv | 1.0.1 | 1 | 1.2.2 | |
| pytest | 8.2.2 | 1 | 9.0.3 | dev only |

Suggested order: pypdf 6.21.2 (patch, upload parsing); remove
google-generativeai (removes protobuf); python-multipart + starlette + FastAPI
together; python-jose → 3.4.0 or PyJWT; Pillow last, with the replay cache.
Every one of these needs the full gate, and Pillow, pypdf and pdfminer changes
need the native-hash comparison as well, since they can change extracted text.

## Frontend — Round 11, superseded by Run 15 above

`npm audit` was **not run**: it sends the dependency tree to the registry
(a POST of the lockfile's packages), which this round's rules exclude. It
should be run by someone who accepts that, or in CI (`npm audit
--omit=dev`).
