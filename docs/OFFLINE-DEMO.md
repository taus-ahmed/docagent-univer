# Offline demo and UI tests: the stub provider

**Development only.** `PRIMARY_LLM=stub` replaces the model with
`backend/engine/connectors/stub_client.py`, which answers every call from the
document text in the request — no network, no key, no cost — so the whole app
can be used in a browser or driven by Playwright: upload, template, extraction,
review, export and the additional options.

```powershell
cd backend
$env:ENVIRONMENT = "development"; $env:PRIMARY_LLM = "stub"
uvicorn app.main:app --port 8000
```

What it does: a field slot is answered with the text after its label on a line
(`Invoice No: INV-1` gives `INV-1`); a table row is a line after the line that
holds the table's headings, trailing numbers right-aligned into the trailing
columns; template inference proposes the `Label:` lines as fields. Every answer
quotes the line it came from, so grounding, the checks and the review marks run
on it exactly as on a real answer. It is not a reader: anything laid out
otherwise comes back empty, and that is expected.

**Refused outside development:** with `ENVIRONMENT=staging` or `production` the
backend does not start if `PRIMARY_LLM` or `LLM_FALLBACKS` names `stub`
(`app/config.py::_refuse_stub_outside_development`). It is never chosen as a
default either: only when named.
