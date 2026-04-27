# Job Hunt Pipeline

## Project Overview
A private, invite-only, multi-user web application that automatically discovers job postings from multiple sources, scores them against user profiles, generates tailored application materials (resume, cover letter, answers, outreach messages), and presents everything for human review before the user applies manually.

**Target roles:** Product Management, AI Automation
**Target geographies:** US, Canada, Europe
**Users:** Small group (3-5 invited users)

## Architecture

### Tech Stack
- **Frontend:** Next.js 14+ (App Router) + Tailwind CSS + shadcn/ui
- **Backend:** Python FastAPI (async)
- **Database:** PostgreSQL via Supabase (connect via Transaction Mode, port 6543 in prod)
- **Auth:** Supabase Auth (invite-only, public signups disabled)
- **Storage:** Supabase Storage (resumes, generated PDFs)
- **Workers:** Celery + Redis (background jobs + Celery Beat for scheduled tasks)
- **Job Discovery:** Apify actors (LinkedIn, Indeed, Google Jobs) + Adzuna + RemoteOK + Arbeitnow + JSearch APIs
- **Page Parsing:** Firecrawl API
- **AI/LLM:** Claude API (Sonnet for parsing/scoring, Opus for tailoring)
- **PDF Generation:** WeasyPrint (HTML/CSS → PDF)
- **Hosting:** Vercel (both frontend AND backend as separate projects) + Supabase (DB/auth/storage). Background jobs run synchronously inside FastAPI request handlers; scheduled discovery runs via Vercel Cron. Celery + Redis are no longer used in production but remain in the codebase for optional local-only use.

### Monorepo Structure
```
job-hunt-pipeline/
├── frontend/          # Next.js app
├── backend/           # FastAPI + Celery workers
│   ├── app/
│   │   ├── api/v1/    # Route handlers
│   │   ├── models/    # SQLAlchemy ORM models
│   │   ├── schemas/   # Pydantic schemas
│   │   ├── services/  # Business logic (discovery, parsing, dedup, scoring, tailoring, pdf, tracking)
│   │   ├── workers/   # Celery task definitions
│   │   ├── llm/       # Claude API client + prompt templates
│   │   └── core/      # Config, database, auth middleware
│   └── alembic/       # Database migrations
├── shared/            # Shared constants
└── docker-compose.yml # Local dev (Postgres + Redis)
```

## Development

### Local Setup
```bash
# Start Postgres + Redis
docker-compose up -d

# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Fill in API keys
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
cp .env.example .env.local  # Fill in Supabase keys
npm run dev
```

### Running Workers (optional, local-only)
Production deploys do not use Celery — discovery runs via Vercel Cron and tailoring runs synchronously inside FastAPI requests. The Celery setup remains for local development if you want to keep work off the request thread.
```bash
# Celery worker
celery -A app.workers.celery_app worker --loglevel=info

# Celery Beat (scheduled tasks)
celery -A app.workers.celery_app beat --loglevel=info
```

### Database Migrations
```bash
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1  # rollback one step
```

## Key Conventions

### Backend
- All DB queries filter by `user_id` from JWT — never return another user's data
- Use async SQLAlchemy with `asyncpg` throughout
- Pydantic schemas for all request/response validation
- Business logic lives in `services/`, not in route handlers
- All external API calls go through dedicated service files in `services/discovery/`
- LLM calls go through `llm/client.py` which handles retries, rate limits, and cost tracking

### Frontend
- App Router (not Pages Router)
- Server components by default, client components only when needed
- TanStack Query for server state management
- shadcn/ui components — do not install other UI libraries
- API client in `lib/api-client.ts` handles auth token injection

### LLM Usage
- **Sonnet** for: job parsing, resume parsing, scoring
- **Opus** for: resume tailoring, cover letters, outreach messages
- **HARD RULE:** Never fabricate experience, tools, metrics, or employers in tailored content
- All generated content validated against candidate's structured profile before showing to user
- Track token usage per call for cost management

### Job Pipeline
Every job flows: Raw → Normalized → Deduplicated → Enriched → Scored → Inbox
- Dedup uses canonical hash (normalized company+title+city+country) + description similarity
- Scoring runs two paths (PM, AI Automation), uses the higher score
- Tailoring only triggered by user action or for high-priority (80+) jobs

### Testing
```bash
cd backend
pytest tests/unit/
pytest tests/integration/
```

## Environment Variables
See `backend/.env.example` and `frontend/.env.example` for all required variables.

## Important Notes
- Public signups are DISABLED in Supabase — users are added via admin invite only
- In production, connect to Supabase PostgreSQL via Transaction Mode (port 6543) with NullPool
- Apify actors trigger via webhooks to `/api/webhooks/apify` — verify HMAC signature
- All tailored application materials require human approval before use

## Deployment (Vercel)

Both frontend and backend deploy as **separate Vercel projects** pointing at the same GitHub repo.

### Backend project
- **Root directory**: `backend`
- **Framework preset**: Other (Vercel auto-detects Python via `vercel.json`)
- **Required env vars**: `DATABASE_URL` (Supabase pooler, port 6543), `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, `ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JSEARCH_RAPIDAPI_KEY`, `CORS_ORIGINS`, `CRON_SECRET`
- **Cron jobs** are defined in `backend/vercel.json` (fast/slow discovery — Vercel Hobby allows max 2)
- **Set `CRON_SECRET`** to any random string; Vercel automatically sends it as `Authorization: Bearer <secret>` to cron endpoints

### Frontend project
- **Root directory**: `frontend`
- **Required env vars**: `NEXT_PUBLIC_API_URL` (the backend's Vercel URL), `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`

### After first deploy
Run the alembic migration once against the production DB:
```bash
cd backend && source venv/bin/activate
DATABASE_URL=<your-supabase-pooler-url> alembic upgrade head
```

### Constraints to know
- Vercel Hobby function timeout is **60 seconds** — tailoring (3-5 LLM calls) usually fits but ~10% of generations may need a retry. Upgrade to Pro for 5-minute timeouts.
- PDF generation is removed in this deploy — replaced with `/dashboard/review/[id]/print` (browser print-to-PDF). To restore PDFs, run the backend on a host that supports cairo/pango (Railway, Fly, Render web services).
- Vercel Hobby allows max 2 Cron jobs.
