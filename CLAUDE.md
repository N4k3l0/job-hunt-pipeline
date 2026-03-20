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
- **Hosting:** Vercel (frontend) + Railway (backend + workers + Redis) + Supabase (DB/auth/storage)

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

### Running Workers
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
- Follow-up reminders run via Celery Beat daily check
