# Testing DocAgent locally and in CI

All normal commands are local and offline. They use recorded model responses and scratch SQLite databases. Do not supply a model key to pytest or replay. Set `DOCAGENT_TEST_NO_DOTENV=1` so the harness does not read any `.env` file.

## T0 survey and baseline

Surveyed on 2026-11-18 from branch `test/acceptance-suite`, starting commit `bbad30997c144338ccca15d623a0bf883dd16d0f`.

- Backend: pytest 8.2.2 is pinned in `backend/requirements-dev.txt`. Tests live in `tests/`; HTTP tests use FastAPI's client and a throwaway SQLite database. The project lint gate is `tests/test_no_undefined_names.py`, backed by pyflakes. No backend type checker or type-check command is configured.
- Replay/accuracy: `python -m tests.harness.runner --mode replay` uses committed responses under `tests/llm_cache/`; `--mode record` is live and must not be used in a normal run. Replay portability depends on the Poppler/Pillow rendering fingerprint.
- Frontend: Node's built-in test runner, TypeScript, and Next build. Tests live beside `frontend/lib/*.ts`.
- CI: `.github/workflows/ci.yml` already had backend/frontend jobs. It now also has `contract-and-replay`; all jobs upload reports.
- Known acceptable environment xfails: exactly the OCR outcome cases guarded by `tests/harness/tesseract_gate.py` when Tesseract is below 5.4. They are strict xfails; fail-closed behavior is still asserted on every version.

Baseline in the supplied worktree:

| Command | Result | Wall time |
| --- | --- | ---: |
| Backend pytest | Environment-blocked before collection: accessible Python had no pytest | 0.07 s |
| Replay harness | Environment-blocked on first document: FastAPI missing | 3.50 s |
| Frontend unit tests | 50 passed, 0 failed | 2.67 s (Node reported 0.77 s test duration) |
| Frontend type-check | Environment-blocked: dependencies not installed | 1.65 s |
| Frontend build | Environment-blocked: dependencies not installed | 1.66 s |

The worktree had no backend virtualenv, no frontend `node_modules`, no Tesseract, and no Poppler. No dependency was downloaded during the baseline because this test session forbids access to hosted services.

## One-time local setup

Use Python 3.11, Node 20 for build/type-check, Node 22.18 or newer for the TypeScript unit tests, Tesseract 5.4 or newer, and Poppler. Install project dependencies from the pinned files:

```powershell
py -3.11 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -r backend\requirements-dev.txt -c backend\constraints.txt
Push-Location frontend
npm.cmd ci
Pop-Location
```

Do not create or load an environment file for tests. Before running, make the offline policy explicit without printing any existing value:

```powershell
$env:DOCAGENT_TEST_NO_DOTENV = "1"
$env:DOCAGENT_REPLAY_ENV = "require"
Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
```

## Exact backend and acceptance commands

Run from the repository root:

```powershell
# Project lint gate
backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_no_undefined_names.py

# Full backend suite: live tests are deselected by pytest.ini
backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --junitxml=backend-tests.xml

# T2-T5 contract, input-lane, export, and scoreboard tests
backend\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\acceptance --junitxml=contract-tests.xml

# Frozen scoreboard report (always writes JSON and Markdown)
backend\.venv\Scripts\python.exe -m tests.tools.score_runs

# Regression gate; it intentionally fails on the recorded baseline until Run A4 lands
backend\.venv\Scripts\python.exe -m tests.tools.score_runs --gate
```

The acceptance suite blocks non-loopback sockets. A test that tries to reach a hosted service fails immediately.

## Exact replay commands

These commands never call a model in replay mode:

```powershell
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode replay
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode replay --no-template
```

Do not use `--mode record` during normal development or CI. The only authorized live path is the separately gated `live-canary` workflow.

## Exact frontend commands

```powershell
Push-Location frontend
npm.cmd run type-check
npm.cmd test
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
npm.cmd run build
Pop-Location
```

## CI checks to require

After this branch is merged by the owner, mark these exact checks as required:

- `ci / backend`
- `ci / frontend`
- `ci / contract-and-replay`

Owner clicks: GitHub repository → **Settings** → **Branches** → add or edit the applicable branch protection rule → enable **Require status checks to pass before merging** → search for and select the three checks above → save changes. This repository setting is intentionally not changed by the test branch.

## Live canary owner setup

The normal workflow has no model key and makes no live calls. The separate `.github/workflows/live-canary.yml` workflow is manual and nightly. It has a hard maximum of 14 HTTP calls, suppresses response bodies on errors, and prints an estimated cost from token usage.

Create the secret with these clicks: GitHub repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret** → name it exactly `GEMINI_API_KEY` → enter the owner-managed key → **Add secret**. Never place the key in a file.

To run manually: **Actions** → **live-canary** → **Run workflow**. The nightly schedule is 07:17 UTC. The report is uploaded as `live-canary-report`.
