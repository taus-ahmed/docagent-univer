# Dependency hygiene (2026-10-23) — report only

Nothing was changed. Every item that touches `backend/requirements.txt`
changes what production installs, so each is a proposal for a reviewed commit
with a production image build (`Dockerfile.backend`) and the full gate.

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

## Known vulnerabilities (Python)

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

## Frontend

`npm audit` was **not run**: it sends the dependency tree to the registry
(a POST of the lockfile's packages), which this round's rules exclude. It
should be run by someone who accepts that, or in CI (`npm audit
--omit=dev`).
