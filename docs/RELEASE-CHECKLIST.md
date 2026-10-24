# Release checklist — before the first push

## 1. One command

```
backend\.venv\Scripts\python.exe scripts\prepush_check.py          # everything (~25 min)
backend\.venv\Scripts\python.exe scripts\prepush_check.py --quick  # repository checks only
```

Read-only on the working tree: the suite, the native readings and both
harness modes run in a clean `git archive HEAD` export in a temporary
directory; the frontend checks run in `frontend/` and write only its ignored
build output. It exits non-zero with a list whenever anything below is not
satisfied. Secrets are reported by path, line and type, never by value.

| Check | Passes when |
|---|---|
| working tree clean | `git status --porcelain` is empty |
| secret scan | no tracked file matches a key pattern (AWS, Google, Groq, OpenAI-style, xAI, GitHub, Slack, private key, JWT, a database URL with a password for a non-local host) |
| machine-specific paths | no Windows profile path, POSIX home path, Git-Bash drive path or local repo path in a tracked file (`tests/llm_cache/` excluded: recorded model traffic) |
| `.env` files | none tracked except `*.example` |
| license | a `LICENSE` file exists — **MANUAL** until one is chosen |
| file size | no tracked file over 5 MB |
| removed provider | "Groq", "Grok" or "xAI" appears only in history docs (`DEPLOY-RUNBOOK`, `ROADMAP`, `SECURITY`, this file, `design-history/`, `DECISION-LOG`) and the test that pins its absence |
| links | every relative link in `README.md` and `docs/**/*.md` resolves |
| CI | every `.github/workflows/*.yml` parses and has `jobs` |
| suite | `pytest` passes in the clean export |
| native readings | `python -m tests.harness.native_hashes --check` matches `tests/reports/native_hashes.json` (69 PDFs) |
| harness | replay, templated EXPORT = 97.2% and no-template EXPORT = 96.7% (`tests/reports/release_baseline.json`) |
| frontend | `npm run type-check`, `npm test`, `npm run build` |

A changed baseline is a decision, not a fix: update `native_hashes.json` or
`release_baseline.json` only in a commit that says why the reading or the
number moved.

## 2. Manual — only Tauseef can do these

The script lists them as MANUAL and fails until run with `--manual-done`.

1. **Revoke the leaked Groq key.** Commit `ecaead9` (2026-04-26, on `main` and
   `origin/main`) has a Groq API key in `.env.example`. History is not
   rewritten; revoke the key at the provider so the copy in history is dead.
2. **Railway variables.** Delete `GROQ_API_KEY`, `GROQ_CLASSIFICATION_MODEL`,
   `GROQ_EXTRACTION_MODEL`, `GROQ_VISION_MODEL` (no longer read); if
   `PRIMARY_LLM` says `groq`, set it to `gemini` or remove it.
3. **`DEMO_CLIENT_IDS`.** Check it names only the demo tenant: every tenant in
   it gets demo limits and the sample-document folder.
4. **License.** Choose one and add `LICENSE`; until then the code is not
   licensed to anyone.
5. **Third-party sample PDFs.** `tests/test_pdfs/round2/` holds public samples
   (CFPB forms, a bank's sample statement, a utility's sample bill, a press
   release). Check their terms allow redistribution in a public repository,
   or keep the repository private, or remove them (the 69-PDF measurements
   would then change and the baselines need a recorded update).
6. **Staging.** Set up the staging environment in `docs/CHEQUE-TRIAL.md` §1
   before any real cheque is uploaded.
7. **Roles.** Decide whether the owner of a job may hard-delete it (today:
   tenant admin and platform admin only) and whether to make `platform_admin`
   an explicit stored role (a data migration) — `docs/proposals/roles.md`.

## 3. After the push

Railway (backend) and Vercel (frontend) deploy from `main`; follow
`docs/DEPLOY-RUNBOOK.md` and confirm the commit SHA is on GitHub.
