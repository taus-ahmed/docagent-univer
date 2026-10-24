# DocAgent

DocAgent turns accounting documents (cheques, invoices, bank statements,
payslips, financial statements, receipts, expense reports) into spreadsheets.
A user draws the spreadsheet they want, uploads PDFs or images, and gets the
spreadsheet back filled in. Every value carries the words it was read from and
a confidence level saying what was actually checked.

The design rule throughout: **review is the backstop, not the quality
mechanism.** A value is verified against the document, or visibly marked
uncertain, or left empty and flagged. Nothing is dropped or merged silently.

## How it works

```
upload (PDF / image)
   │
   ▼
preprocess ── native text layer (pdfplumber), or OCR through the reader seam
   │          (Tesseract); one origin per page: native | ocr
   ▼
document boundaries ── one file may hold several documents
   │
   ▼
template grid ──► shape ──► one model call per document (Gemini):
   ▲                         every empty template cell is an addressed slot,
   │                         answered with {value, source quote, page}
   └── no template? the model designs one first, then the same path
   │
   ▼
grounding ── each quote is checked against the page text, independently of
   │         the model; numbers must equal a printed number
   ▼
family validators ── cheque amounts and MICR, invoice / bank / payslip totals
   │
   ▼
confidence + review gates ──► Excel export with provenance
```

| Part | Where |
|---|---|
| API (FastAPI, JWT auth, multi-tenant by `client_id`) | `backend/app/` |
| Extraction engine | `backend/engine/` |
| Web app (Next.js 14) | `frontend/` |
| Tests, accuracy harness, gold corpus, recorded model answers | `tests/` |
| Design documents | `docs/` |

## Setup

Requirements: Python 3.11, Node 20, PostgreSQL 14+, and on the PATH
**Poppler** (`pdf2image`) and **Tesseract** with English data (OCR).

```bash
# backend
cd backend
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt -c constraints.txt
cp .env.example .env        # fill in DATABASE_URL, GEMINI_API_KEY, SECRET_KEY
uvicorn app.main:app --reload --port 8000      # start from backend/

# frontend
cd frontend
npm ci
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev                 # http://localhost:3000
```

`docker-compose up -d` starts PostgreSQL and the backend instead. Every
environment variable the code reads is listed in `backend/.env.example`.

## Tests

```bash
pip install -r backend/requirements-dev.txt -c backend/constraints.txt
python -m pytest                                        # offline: replays recorded model answers
python -m tests.harness.runner --mode replay            # accuracy over the gold documents
python -m tests.harness.runner --mode replay --no-template
```

The suite makes no network calls: every model answer it needs is stored in
`tests/llm_cache/`. `--mode record` calls the live model and costs money.
`tests/README.md` describes the harness, the gold labels and the scorer.

## Deploy

The backend runs on Railway (`Dockerfile.backend`, PostgreSQL service) and the
frontend on Vercel; both deploy from `main`. The procedure, the checks before
and after, storage on Cloudflare R2 and rollback are in
`docs/DEPLOY-RUNBOOK.md` and `docs/R2-SETUP.md`.

## Documentation

| Document | Contents |
|---|---|
| `CLAUDE.md` | developer guide: the engine's rules, the result contract, the backend and frontend architecture, gotchas |
| `docs/ENGINE-RESULT-CONTRACT.md` | the result every engine record returns, key by key |
| `docs/OCR-READER-SEAM-DESIGN.md` | scanned pages, the OCR seam, review gates, reason codes (§12), validators |
| `docs/DECISION-LOG.md` | why the engine is the way it is, and what was rejected |
| `docs/KNOWN-LIMITATIONS.md` | what the system does not do yet, in plain language |
| `docs/ROADMAP.md` | what is done and what remains |
| `docs/proposals/` | measured proposals not yet built |
| `docs/TEMPLATE-SHAPE-FUTURE-WORK.md` | the deferred declared-shape migration |
| `docs/SECURITY.md` | authentication, tenancy, secrets and known gaps |
| `docs/investigations/` | dated measurement records cited by code and tests |

## License

No license has been chosen yet. Until one is added, all rights are reserved.
