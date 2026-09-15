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
- Job descriptions are written by job boards and scrapers: the job page renders only `description_html` (sanitized with nh3 in `services/parsing/html_text.py`). Never render `raw_description` or `raw_description_en` as HTML
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
- **Sonnet 5** (`claude-sonnet-5`) for: job parsing, resume parsing, deep reviews, web search, drafting application-form answers (`applying`)
- **Opus 5** (`claude-opus-5`) for: resume tailoring, cover letters, outreach messages
- Model IDs and per-task effort live only in `llm/client.py` (`MODELS`, `EFFORT`). Don't pass `temperature` — current models and SDK 1.x reject it
- **HARD RULE:** Never fabricate experience, tools, metrics, or employers in tailored content
- All generated content validated against candidate's structured profile before showing to user
- Track token usage per call for cost management

### Job Pipeline
Every job flows: Raw → Normalized → Deduplicated → Enriched → Scored → Inbox
- Dedup uses canonical hash (normalized company+title+city+country) + description similarity
- Enrichment: `/api/v1/cron/enrich` reads recent jobs with Haiku (skills, requirements, seniority, salary with its period, sponsorship, `eligible_countries`), then rescores them for every user. The best-scored jobs for any user are read first: an unread job's level and skills are unknown, which keeps its score down
- Scoring (`services/scoring/scorer.py` + `matching.py`) is the same for every profession: title vs target roles/interests/recent titles, skills overlap, seniority, industry, remote fit; blended with Voyage resume/job embeddings only when `EMBEDDINGS_ENABLED=true` and `VOYAGE_API_KEY` is set (off in production). It must stay fast: a full rescore covers the whole catalog inside 60s
- Scoring versions: `SCORE_VERSION` is what `job_scores` stores; `PROPOSED_SCORE_VERSION` is the next one, not live yet. Version 3 gives nothing for what isn't known (a level or remote policy the job doesn't state counts as 0; a part the profile has nothing for is left out and the other weights share its weight) and holds jobs matching neither the user's roles nor their skills at 45, below the inbox's 50
- Rate matches (`/dashboard/rate`, `/api/v1/ratings`, `job_ratings`): users say whether jobs fit them without seeing scores. `services/scoring/evaluation.py` scores the rated jobs live with both versions and compares them with the ratings. Measure a scoring change there before it goes live; to switch, set `SCORE_VERSION` to the proposed version, deploy, then rescore every user (`/api/v1/cron/score-backlog?rescore_all=true`)
- Hard filters (`services/jobs_filter.py`) hide jobs per user: preferred countries, remote preference, remote roles restricted away from the user's home country, no sponsorship where the user needs it, and source-stated salary below the user's minimum. A job that doesn't state a fact is never hidden by it
- Inbox relevance: a job's title matches the user's roles or skills, or its score shows a skill match (`job_scores.skill_score > 0`). Never filter inbox queries on `raw_description`: ~83 MB of text across 12k jobs made each query take ~25s
- Discovery sources keep location-restricted jobs and tag `eligible_countries`; they don't drop them
- `/api/v1/cron/review-top-matches` runs deep reviews on each user's best new matches, capped per user per day
- Freshness: ingest sets `jobs.last_seen_at` whenever a source lists a job again. `/api/v1/cron/expire-stale` expires jobs gone from full company boards (`curated`, unseen 5 days) and jobs older than 45 days that no source has listed for 30 days, then probes a batch of links (`last_checked_at`, 404/410 → expired). Jobs a user applied to or tailored for are never expired; old shortlisted ones are kept
- Resume upload doesn't rescore inline (parse + full rescore can exceed 60s); the frontend calls `POST /candidates/rescore` afterwards
- Tailoring only triggered by user action or for high-priority (80+) jobs

### LinkedIn job alerts (`services/job_alerts/`, `/api/v1/job-alerts`)
- Each user runs a Google Apps Script in the Gmail account that gets their LinkedIn job alerts. Profile → Preferences writes it with their key (`frontend/src/lib/linkedin-alert-script.ts`). Every hour it sends new emails from `jobalerts-noreply@linkedin.com` to `POST /job-alerts/linkedin` with `Authorization: Bearer jha_…`. Only the key's SHA-256 is stored (`job_alert_keys`)
- The script strips every link's query string except `trk`: LinkedIn's links carry one-time sign-in codes (`otpToken`, `midToken`). The backend never stores the email, only the jobs read from it
- `linkedin.py` reads the jobs from the email: the job id from each `/jobs/view/<id>` link, the section and position from `trk` (`primary_job_list-0-jobcard_body_1_jobid_…`), then title, "Company · Location (Remote)", salary and labels. Parsing lives in the backend so layout changes don't need every user to update their script
- `ingest.py`: one job row per LinkedIn id for everyone (`linkedin_jobs`); a job the app already has (same link, or same company, title, city and country) is reused and reopened if expired. `job_alert_hits` records per user which jobs their alerts sent; `job_alert_emails` makes a resent email a no-op
- Alert emails have no description. `/cron/job-alert-details` (every scheduler run) looks each new job up once on the company's own job board (`ats_resolver.resolve_ats_url`, then the Greenhouse/Lever/Ashby posting APIs). Free: no LinkedIn pages, Firecrawl or Claude
- Rate matches samples up to 10 alert jobs whatever their score and reports how often the user rates them good. "LinkedIn sent it" doesn't change scores until ratings show it should

### Apply for me (`services/auto_apply/`, `/api/v1/auto-apply`)
- Supported: jobs whose `apply_url`/`job_url` is on Greenhouse, Lever or Ashby (`ats.py`). Greenhouse and Ashby publish each job's form as JSON; Lever's is read from its apply page (`forms.py`). All three forms carry invisible bot checks (reCAPTCHA / hCaptcha): never build anything that gets around them
- `prepare_application` reads the form, fills answers from the profile with rules (`answers.py`), then drafts the remaining required questions in one Claude call (`drafting.py`). Every answer records its `source` and whether it's `confirmed`
- Only confirmed answers come from facts: profile and resume, the user's earlier answer to the same question (`saved_answers`, confirmed for 30 days), declining voluntary demographic questions and marketing messages. Suggested and drafted answers always need the user
- Legal agreements, acknowledgements and attestations are never answered for the user, even when required. Work authorization and sponsorship are answered only when `home_country`/`visa_statuses` settle them for the job's country
- Statuses: `needs_you` until every required question is answered and confirmed, then `queued` once the user approves (`PUT /{id}/answers` with `approve`). Nothing sends applications yet: approved ones are sent by hand from the form link

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
- In production, connect to Supabase PostgreSQL via Transaction Mode (port 6543). `DB_POOL_SIZE` picks the connection handling (`core/database.py`): `0` opens one per request (Vercel), above `0` keeps connections open (Railway)
- Apify actors trigger via webhooks to `/api/webhooks/apify` — verify HMAC signature
- All tailored application materials require human approval before use

## Deployment (Vercel)

Both frontend and backend deploy as **separate Vercel projects** pointing at the same GitHub repo.

### Backend project
- **Root directory**: `backend`
- **Region**: `dub1` (Dublin, set in `backend/vercel.json`), next to the Supabase database in AWS eu-west-1. Keep them together: every request opens a fresh database connection
- **Framework preset**: Other (Vercel auto-detects Python via `vercel.json`)
- **Required env vars**: `DATABASE_URL` (Supabase pooler, port 6543), `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, `ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JSEARCH_RAPIDAPI_KEY`, `CORS_ORIGINS`, `CRON_SECRET`
- **No cron jobs**: scheduled work runs on Railway (below). The Vercel backend stays deployed only as a rollback target

### Backend on Railway
The website (`NEXT_PUBLIC_API_URL`) uses the Railway backend: no time limit on requests, and room for the auto-apply worker. To roll back, set it back to `https://backend-nakel0s-projects.vercel.app`, redeploy the frontend, and restore the crons in `backend/vercel.json` from git history.
- **Project** `job-hunt-pipeline`, service `backend`, https://backend-production-7e805.up.railway.app
- **Build**: `backend/Dockerfile` (uvicorn on `$PORT`, two processes via `WEB_CONCURRENCY`)
- **Service settings** live on Railway, not in the repo (Railway ignores `railway.json` now): region EU West / Amsterdam (`europe-west4-drams3a`), health check `/health`, restart on failure up to 5 times
- **Env vars**: the same as the Vercel backend, plus `DB_POOL_SIZE=5`
- **Deploys** automatically from GitHub `main` (root directory `/backend`, watch paths `/backend/**`). `cd backend && railway up --service backend` deploys the local checkout instead
- Cron endpoints refuse every request until `CRON_SECRET` is set, and the Apify webhook until `APIFY_WEBHOOK_SECRET` is

### Scheduler on Railway
Service `scheduler` in the same project is a Railway cron service: every 30 minutes (`*/30 * * * *`) it runs `python scripts/scheduled_tasks.py` from the backend image and exits. That script calls the backend's cron endpoints: discovery at 06:00 (`discover-fast`) and 06:30 UTC (`discover-remote`), and on every run `enrich`, `expire-stale` and, when `REVIEWS_PER_USER_PER_DAY` > 0, `review-top-matches`.
- **Env vars**: `BACKEND_URL` (`https://${{backend.RAILWAY_PUBLIC_DOMAIN}}`), `CRON_SECRET` (`${{backend.CRON_SECRET}}`), `ENRICH_JOBS_PER_RUN` (25), `REVIEWS_PER_USER_PER_DAY` (0). Both references point at the backend service, so there's one secret to rotate
- **Run by hand**: `python scripts/scheduled_tasks.py --discovery both` runs discovery regardless of the time. `.github/workflows/scheduled-grading.yml` remains as a manual fallback (workflow_dispatch only)
- Railway skips a run while the previous one is still going, and each run's log shows every endpoint's response

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
