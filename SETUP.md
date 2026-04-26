Ṁ# DocAgent v2.0 — Phase 1 Setup Guide

## What's in this package

```
docagent-v2/
├── backend/
│   ├── app/
│   │   ├── main.py                  ← FastAPI app factory + lifespan
│   │   ├── config.py                ← Pydantic-settings config (reads .env)
│   │   ├── api/routes/
│   │   │   ├── auth.py              ← POST /api/auth/login, GET /me
│   │   │   ├── extract.py           ← POST /api/extract/upload, GET /api/jobs/*
│   │   │   ├── export.py            ← POST /api/export/combined + /perfile
│   │   │   ├── templates.py         ← CRUD /api/templates
│   │   │   ├── schemas.py           ← CRUD /api/schemas
│   │   │   ├── drive.py             ← Drive OAuth + /api/watch
│   │   │   └── admin.py             ← /api/admin/users + /stats
│   │   ├── core/
│   │   │   ├── auth.py              ← JWT creation, password hashing, FastAPI deps
│   │   │   └── storage.py           ← Local/S3 file storage abstraction
│   │   ├── models/
│   │   │   └── models.py            ← SQLAlchemy models (PostgreSQL)
│   │   └── schemas/
│   │       └── schemas.py           ← Pydantic request/response schemas
│   ├── engine/                      ← Your prototype files (copied in)
│   │   ├── orchestrator.py
│   │   ├── preprocessor.py
│   │   ├── prompt_builder.py
│   │   ├── validator.py
│   │   ├── excel_writer.py
│   │   ├── base_prompts.py
│   │   ├── groq_client.py
│   │   ├── gemini_client.py
│   │   ├── llm_router.py
│   │   ├── gdrive.py
│   │   ├── drive_watcher.py
│   │   └── demo_accounting.yaml
│   ├── alembic/
│   │   └── env.py                   ← DB migrations config
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── lib/
│   │   ├── api.ts                   ← Full typed API client (all endpoints)
│   │   └── auth-store.ts            ← Zustand auth store
│   ├── package.json
│   └── next.config.js
├── docker-compose.yml
└── .gitignore
```

---

## Step 1 — Project initialization (Windows 11)

Open PowerShell or Windows Terminal and run:

```powershell
# 1. Navigate to where you want the project
cd C:\Users\YourName\Projects

# 2. Create and enter the project root (unzip the package here)
# The docagent-v2/ folder should now exist

cd docagent-v2
```

---

## Step 2 — PostgreSQL database setup

```powershell
# Create the database (PostgreSQL must be running)
psql -U postgres -c "CREATE USER docagent WITH PASSWORD 'docagent';"
psql -U postgres -c "CREATE DATABASE docagent OWNER docagent;"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE docagent TO docagent;"
```

Test the connection:
```powershell
psql -U docagent -d docagent -c "SELECT version();"
```

---

## Step 3 — Backend setup

```powershell
cd backend

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
copy .env.example .env
# Now edit .env — at minimum set:
#   DATABASE_URL=postgresql://docagent:docagent@localhost:5432/docagent
#   GROQ_API_KEY=gsk_...
#   SECRET_KEY=<run: python -c "import secrets; print(secrets.token_hex(32))">
notepad .env
```

### Run database migrations

```powershell
# Initialize Alembic (first time only)
alembic upgrade head

# If you need to generate a new migration after model changes:
# alembic revision --autogenerate -m "describe your change"
# alembic upgrade head
```

### Start the FastAPI server

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit http://localhost:8000/docs — you should see the Swagger UI with all endpoints.

Default admin credentials: **admin / admin123** (change immediately!)

---

## Step 4 — Verify the backend

```powershell
# Health check
curl http://localhost:8000/health

# Login (should return a JWT token)
curl -X POST http://localhost:8000/api/auth/login `
  -H "Content-Type: application/json" `
  -d '{"username": "admin", "password": "admin123"}'

# List schemas (should show demo_accounting)
curl http://localhost:8000/api/schemas `
  -H "Authorization: Bearer <token_from_login>"
```

---

## Step 5 — Frontend setup

```powershell
cd ..\frontend

# Install dependencies
npm install

# Environment file
copy .env.local.example .env.local
# OR create manually:
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Start dev server
npm run dev
```

Visit http://localhost:3000

---

## Step 6 — Test a full extraction

Using the Swagger UI at http://localhost:8000/docs:

1. **POST /api/auth/login** → get your JWT token
2. Click "Authorize" in Swagger, paste the token
3. **GET /api/schemas** → confirm `demo_001` schema exists
4. **POST /api/extract/upload** → upload a PDF invoice with `client_id=demo_001`
5. **GET /api/jobs/{job_id}** → poll until `status: "completed"`
6. **GET /api/jobs/{job_id}/results** → see extracted data
7. **POST /api/export/combined** with `{"job_id": <id>}` → download Excel

---

## Engine import path notes

The prototype engine files live in `backend/engine/`. The backend routes add this
to `sys.path` at runtime so imports like `from orchestrator import Orchestrator` work.

The engine files still import from their own `config.py` — that's fine for Phase 1.
In Phase 2 we'll refactor them to use `app.config.settings` directly.

---

## Quick SQLite fallback (no PostgreSQL)

If you want to skip PostgreSQL for now, edit `.env`:

```
DATABASE_URL=sqlite:///./storage/docagent.db
```

Everything works — just swap back to PostgreSQL before deploying.

---

## Architecture notes for the next phases

### Phase 2 — Frontend (Next.js)
Build the pages using the API client already scaffolded in `frontend/lib/api.ts`:
- `/login` — auth form → calls `authApi.login()`
- `/extract` — file dropzone + schema selector + AG Grid results table
- `/history` — job list with status badges
- `/templates` — column template manager
- `/admin` — user management + stats dashboard

### Phase 3 — S3 Storage
Set `STORAGE_BACKEND=s3` in `.env` and fill in AWS/R2 credentials.
The `StorageService` in `app/core/storage.py` handles everything — no route changes needed.

### Phase 4 — Celery + Redis
The `_run_extraction_sync()` function in `extract.py` is the exact code that goes
into a Celery task. The swap is mechanical:
1. Install Redis: `winget install Redis.Redis`
2. Move the function to `app/workers/tasks.py`
3. Replace `thread = threading.Thread(...)` with `run_extraction.delay(job_id, ...)`

### Phase 5 — Deploy
- Backend → Railway (Dockerfile ready, just set env vars)
- Frontend → Vercel (`npm run build` → deploy)
- Database → Railway PostgreSQL or Supabase
- Files → Cloudflare R2 (set STORAGE_BACKEND=s3 + R2 credentials)

---

## Common issues

**"Schema not found for client_id"**
The demo schema auto-seeds on first startup. If it's missing, POST a YAML to
`/api/schemas` using the demo_accounting.yaml file.

**"No module named 'orchestrator'"**
The engine's sys.path injection happens at request time. Make sure you started uvicorn
from the `backend/` directory (not the project root).

**PostgreSQL connection refused**
Make sure the PostgreSQL service is running:
```powershell
Get-Service -Name postgresql*
Start-Service postgresql-x64-14
```

**pdf2image fails (no poppler)**
Install poppler for Windows:
```powershell
winget install poppler
# OR manually: https://github.com/oschwartz10612/poppler-windows/releases
# Add the bin/ folder to PATH
```
The system degrades gracefully — text-based PDFs still work without poppler.
