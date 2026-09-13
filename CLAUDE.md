# Job Hunt Pipeline

## Project Overview
A private, invite-only, multi-user web application that automatically discovers job postings from multiple sources, scores them against user profiles, generates tailored application materials (resume, cover letter, answers, outreach messages), and presents everything for human review before the user applies manually.

**Target roles:** any profession (grading is profession-agnostic)
**Target geographies:** set per user (preferred countries + home country)
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
export PYTHONPATH=.  # alembic/env.py imports the app package
alembic revision --autogenerate -m "description"
alembic upgrade head
alembic downgrade -1  # rollback one step
```
Keep a single head: `alembic heads` should print one revision.

## Key Conventions

### Backend
- All DB queries filter by `user_id` from JWT — never return another user's data
- `jobs` rows are shared by all users. Never write per-user state to `jobs.status`: shortlist/dismiss go in `user_job_states`, applied state in `application_tracking` (see `services/job_state.py`)
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
- **Haiku 4.5** (`claude-haiku-4-5`) for: reading every incoming job (`services/enrichment/job_enricher.py`)
- **Sonnet 5** (`claude-sonnet-5`) for: job parsing, resume parsing, deep reviews, web search
- **Opus 5** (`claude-opus-5`) for: resume tailoring, cover letters, outreach messages
- Model IDs and per-task effort live only in `llm/client.py` (`MODELS`, `EFFORT`). Don't pass `temperature` — current models and SDK 1.x reject it
- **HARD RULE:** Never fabricate experience, tools, metrics, or employers in tailored content
- All generated content validated against candidate's structured profile before showing to user
- Track token usage per call for cost management

### Job Pipeline
Every job flows: Raw → Normalized → Deduplicated → Enriched → Scored → Inbox
- Dedup uses canonical hash (normalized company+title+city+country) + description similarity
- Enrichment: `/api/v1/cron/enrich` reads recent jobs with Haiku (skills, requirements, seniority, salary with its period, sponsorship, `eligible_countries`), then rescores them for every user
- Scoring (`services/scoring/scorer.py` + `matching.py`) is the same for every profession: title vs target roles/interests/recent titles, skills overlap, seniority, industry, remote fit; blended with resume embeddings when Voyage is available. It must stay fast: a full rescore covers the whole catalog inside 60s
- Hard filters (`services/jobs_filter.py`) hide jobs per user: preferred countries, remote preference, remote roles restricted away from the user's home country, no sponsorship where the user needs it, and source-stated salary below the user's minimum. A job that doesn't state a fact is never hidden by it
- Discovery sources keep location-restricted jobs and tag `eligible_countries`; they don't drop them
- `/api/v1/cron/review-top-matches` runs deep reviews on each user's best new matches, capped per user per day
- Freshness: ingest sets `jobs.last_seen_at` whenever a source lists a job again. `/api/v1/cron/expire-stale` expires jobs gone from full company boards (`curated`, unseen 5 days) and jobs older than 45 days that no source has listed for 30 days, then probes a batch of links (`last_checked_at`, 404/410 → expired). Jobs a user applied to or tailored for are never expired; old shortlisted ones are kept
- Resume upload doesn't rescore inline (parse + full rescore can exceed 60s); the frontend calls `POST /candidates/rescore` afterwards
- Tailoring only triggered by user action or for high-priority (80+) jobs

### Testing
```bash
cd backend
pytest tests/unit/
# Integration tests need a disposable Postgres with pgvector, migrated to
# head, whose database name contains "test". They TRUNCATE tables.
TEST_DATABASE_URL=postgresql://user@localhost:5432/jobhunt_test pytest tests/integration/
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
- **Enrichment and top-match reviews** run from `.github/workflows/scheduled-grading.yml` every 30 minutes. It is off until the repo variable `GRADING_SCHEDULE_ENABLED` is `true`, and needs secret `CRON_SECRET` and variable `BACKEND_URL`
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
