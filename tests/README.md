# Accuracy harness

This directory is the measurement layer for the extraction pipeline: gold
labels, a type-aware scorer, a runner that produces accuracy reports, an LLM
record/replay cache, and pytest wiring. Its job is to make "the extracted value
is wrong" impossible to miss.

## Layout

```
tests/
  conftest.py            pytest fixtures + environment bootstrap
  harness/
    bootstrap.py         env/sys.path setup (production-parity extraction config)
    adapter.py           engine output -> flat {fields, tables} (ONLY place that
                         knows the engine's output schema)
    scoring.py           type-aware comparison, 4-outcome classification, table
                         row alignment
    llm_cache.py         record/replay of LLM responses at the LLMRouter chokepoint
    runner.py            CLI: run pipeline over labeled docs, score, report, diff
  gold/
    labels/*.json        ground-truth labels, one flat JSON per document
    templates/*.json     spreadsheet-grid templates the runner extracts with
    README.md            label schema + labeling policy
  llm_cache/*.json       recorded raw LLM responses (committed, for offline replay)
  reports/               runner output; latest.json is the committed baseline
  test_pdfs/             63 synthetic fixture PDFs (pre-existing)
  test_scoring.py        unit tests for the scorer itself (offline, green)
  test_adapter.py        unit tests for the output adapter (offline, green)
  test_known_bugs.py     tests that reproduce known unfixed bugs — FAIL on purpose
```

## Running

```powershell
# from the repo root, using the backend venv
backend\.venv\Scripts\python.exe -m pytest            # offline, all green

# accuracy run over all labeled documents (offline, replays cached LLM responses)
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode replay

# live run against Gemini (costs money; records responses into tests/llm_cache/)
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode record

# stability check: run each doc N times live, flag fields whose value varies
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode record --repeat 3
```

The runner writes `tests/reports/latest.json` (machine-readable),
`tests/reports/latest.md` (human summary), a timestamped copy under
`tests/reports/history/`, and prints a diff against the previous `latest.json`
— every field that changed state is listed, and `correct -> wrong` transitions
are called out as REGRESSIONS.

## What the harness measures

The runner drives the real pipeline in-process (`_extract_with_template`, no
HTTP, no DB) under **production-parity config**: `PRIMARY_LLM=gemini`,
`GEMINI_MODEL=gemini-2.5-flash-lite` — the audited Railway configuration.
(`USE_NEW_EXTRACTOR` was removed in Phase 2d; there is one pipeline now.) Each gold document is extracted with a committed
template in `tests/gold/templates/` whose requested fields match the gold
label file, so `missed` means "the engine was asked and returned nothing",
never "the engine wasn't asked".

Phase 2d deleted the bare-except fallback that used to swap engines mid-request
(audit finding D4). The runner still watches for its log marker, so a
reappearance would be caught rather than absorbed.

## The old test files: replaced, not repaired

`tests/test_extraction.py` and `tests/test_results.json` were **removed** in
favor of this harness. Reasons:

- It required a live server and hardcoded `admin`/`admin123`, which production
  rejects (401) — the suite could not log in to its own default target.
- It validated **shape, not correctness**: zero `assert` statements, and its
  pattern checks (`Amount: ^\d+(\.\d{1,2})?$`) pass for any number whatsoever.
  A cheque for $1,250.00 extracted as $9,999.99 passed every check.
- Its last recorded run (2026-05-05) executed checks on 5 of 60 documents.

Nothing in it was worth carrying over: the doc-type schema lists survive in
git history if ever needed, and value-level ground truth (which it never had)
now lives in `tests/gold/labels/`.

## Ground-truth policy

Labels were produced by reading each PDF's pdfplumber text directly and
cross-checking arithmetic (line items sum to subtotals, debits/credits
reconcile to closing balance, etc.). They were **not** produced by running the
extraction pipeline — that would only measure whether the pipeline agrees with
itself. When the engine's output schema changes, update `harness/adapter.py`;
never regenerate label files from engine output.
