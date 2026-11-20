# Model migration: gemini-2.5-flash → Gemini 3.x (overnight M3)

Read from Google's documentation on **2026-11-20**. The `ai.google.dev/gemini-api/docs/*`
pages now redirect (HTTP 301) to `aistudio.google.com/docs/*`; the URLs below are the
redirect targets. **Nothing here was verified with a live call** — the model matrix
(`tools/model_matrix.py`, below) is that check.

## Why now

- **gemini-2.5-flash is deprecated.** "Effective December 1, 2026, all API requests to
  `gemini-2.5-flash` will automatically route to `gemini-3.5-flash-lite`"
  (aistudio.google.com/docs/deprecations, /docs/models/gemini-2.5-flash). Access is limited
  to existing users. Railway production runs `gemini-2.5-flash-lite` (CLAUDE.md); the code
  default is `gemini-2.5-flash`.
- **gemini-2.5-flash-lite** is not deprecated: "will continue to be served until further
  notice", no shutdown date.
- A routed request would have been recorded under the name we ASKED for. Since M2,
  `document_results.model_used` stores the `modelVersion` the API returned, and the
  Legend says "Extracted by: …".

## The models

| model | id | input / output limit | thinking | default level | price / 1M in · out |
|---|---|---|---|---|---|
| gemini-2.5-flash | `gemini-2.5-flash` | 1,048,576 / 65,536 | yes | on | not on the pages read (engine table: $0.30 · $2.50) |
| gemini-2.5-flash-lite | `gemini-2.5-flash-lite` | 1,048,576 / 65,536 | yes | off | not on the pages read (engine table: $0.10 · $0.40) |
| gemini-3.5-flash-lite | `gemini-3.5-flash-lite` | 1,048,576 / 65,536 | levels minimal / low / medium / high | minimal | $0.30 · $2.50 |
| gemini-3.6-flash | `gemini-3.6-flash` | 1M context / 64k output | levels minimal / low / medium / high | medium | $1.50 · $7.50 |
| gemini-3.8-flash | `gemini-3.8-flash` | 1,048,576 / 65,536 | levels low / medium / high — "`minimal` is not supported and returns an error" | medium | $0.75 · $3.75 to 2026-12-31, then $1.50 · $7.50 |

Sources: /docs/models/gemini-3.5-flash-lite, /docs/whats-new-gemini-3.6, /docs/whats-new-gemini-3.8,
/docs/models/gemini-3.8-flash, /docs/models/gemini-2.5-flash, /docs/models/gemini-2.5-flash-lite,
/docs/thinking, /docs/changelog (2026-11-02 entry), /docs/deprecations.

## Breaking changes that touch our client (`backend/engine/connectors/gemini_client.py`)

| area | what we send today | what the 3.x docs say | what the code now does |
|---|---|---|---|
| **thinking** | `generationConfig.thinkingConfig.thinkingBudget` (when `GEMINI_THINKING_BUDGET` is set) | "`thinking_level` replacing `thinking_budget`" is listed as a breaking change; levels as in the table; no documented "off" | 3.x profiles send `thinkingConfig.thinkingLevel`; 2.5 keeps `thinkingBudget` |
| **temperature** | `generationConfig.temperature` (0 since A6) | temperature, top_p, top_k are deprecated: "The API ignores these parameters and returns an error in future model generations" | 3.x profiles do not send temperature. Determinism on 3.x then rests on the model alone |
| **structured output** | `responseMimeType: application/json` + `responseSchema` | "Structured outputs" listed as supported; field names not documented on the pages read | unchanged |
| **max output tokens** | `GEMINI_MAX_OUTPUT_TOKENS` (8192), doubled once on MAX_TOKENS | 65,536 (3.6: 64k) | capped per profile; 2.5 unchanged |
| **response fields** | `candidates[].content.parts`, `usageMetadata.*` incl. `thoughtsTokenCount`, `modelVersion`, `finishReason` | **not documented on the pages read** — the docs now centre on the Interactions API (`POST /v1beta/interactions`, `generation_config.thinking_level`) | unchanged; **not verified** |
| **API surface** | `generateContent` (v1beta REST) | Interactions API is the documented path; generateContent is mentioned (3.8: every `FunctionResponse` needs `call_id` and `name` — we send none) | unchanged; **not verified** that generateContent accepts `thinkingLevel` in camelCase |

## Per-model settings (configurable)

`gemini_client.MODEL_PROFILES`, longest-prefix match on the model id, overridable with
`GEMINI_MODEL_PROFILES` (a JSON object `{model-prefix: {key: value}}`):

| key | meaning | gemini-2.5 (today) | 3.5-flash-lite | 3.6-flash | 3.8-flash |
|---|---|---|---|---|---|
| `temperature` | send `temperature` | true | false | false | false |
| `thinking` | `budget` or `level` | budget | level | level | level |
| `thinking_level` | level sent | — | minimal | low | low (never minimal) |
| `max_output` | cap on `maxOutputTokens` | 65536 | 65536 | 64000 | 65536 |

`tests/test_overnight_m3.py` pins that gemini-2.5-flash's request body is exactly what it
was before. An unknown model gets the 2.5 profile.

Example override: `GEMINI_MODEL_PROFILES={"gemini-3.6-flash": {"thinking_level": "medium"}}`.

## No silent switch (M1)

The built-in candidate list (including `gemini-flash-latest` / `gemini-flash-lite-latest`) is
gone. `GEMINI_MODEL_FALLBACKS` (default empty) lists the only models tried after a 404; with
none, a 404 fails the document: "model not found (HTTP 404): gemini-… — no other model was
used".

## The matrix (owner runs it; NOT run overnight)

```powershell
$env:GEMINI_API_KEY = "<key>"     # read from the environment only; never from .env
backend\.venv\Scripts\python.exe -m tools.model_matrix
```

8 documents (`pitt_sample_w2`, `irs_w2_mod11`, `irs_1099int_mod3`, `irs_1099nec_ellis`,
`flowparse_bank_us`, `mammoth_2pg`, `flowparse_invoice_tax`, `flowparse_po`) × 5 models
(`gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.5-flash-lite`, `gemini-3.6-flash`,
`gemini-3.8-flash`), document-major. Results: `local_docs/job_records/matrix/<model>/<doc>.json`,
`summary.json`, `summary.md`, scored by `tests/tools/score_runs.py` against `tests/golden`.
Hard caps counted at HTTP level by `tests/tools/live_cap.py`: **50 requests, USD 1.00**
(`LIVE_CAP_MAX_CALLS` / `LIVE_CAP_MAX_USD` may lower them, never remove them). 40 cells at one
or more requests each means the cap can stop the run; it stops between cells and the summary
says where. Extraction runs at `EXTRACTION_TEMPERATURE=0` (production).

## Open questions the matrix answers

1. Does generateContent accept `thinkingConfig.thinkingLevel` (camelCase) for 3.x, or only the
   Interactions API's `thinking_level`? A 400 on the first 3.x cell says which.
2. Do 3.x models still return `usageMetadata.thoughtsTokenCount` and `modelVersion`?
   (`summary.md`'s Version column, and the attempt records.)
3. Is `responseSchema` honoured, or is `responseJsonSchema` required?
4. Accuracy and silent defects per model against the golden files.
