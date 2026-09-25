# Job Hunt Pipeline

## Project Overview
A private, invite-only, multi-user web application that discovers job postings from many sources, scores them against each user's profile, prepares tailored application materials and application-form answers, and presents everything for the user's review. The goal is applying automatically; today the user approves every application and sends it.

**Target roles:** any profession (grading is profession-agnostic)
**Target geographies:** set per user (preferred countries + home country)
**Users:** Small group (3-5 invited users)

## Architecture

### Tech Stack
- **Frontend:** Next.js 14+ (App Router) + Tailwind CSS + shadcn/ui
- **Backend:** Python FastAPI (async)
- **Database:** PostgreSQL via Supabase (connect via Transaction Mode, port 6543 in prod)
- **Auth:** Supabase Auth (invite-only, public signups disabled)
- **Storage:** Supabase Storage (resumes, private bucket with signed links)
- **Scheduled work:** a Railway cron service calls the backend's `/api/v1/cron/*` endpoints (see "Scheduler on Railway"). There is no queue or worker process; `app/workers/` holds plain async functions the endpoints call
- **Job Discovery:** company job boards (Greenhouse, Lever, Ashby), JSearch, Arbeitnow, RemoteOK, Himalayas, Remotive, We Work Remotely, DailyRemote, Undutchables, Working Nomads, Wellfound, Jobberman, MyJobMag, and users' LinkedIn job alert emails
- **Page Parsing:** job board pages are fetched directly with an honest user agent (`services/discovery/firecrawl_service.py`); Firecrawl is only the fallback for a page that doesn't come back, and is left alone for an hour after it answers 429. A site that blocks direct requests or shows a human check is never worked around
- **AI/LLM:** Claude API (see "LLM Usage")
- **Tailored resume PDFs:** drawn by the backend with fpdf2 (`services/auto_apply/resume_pdf.py`) so applications can attach them; `/dashboard/review/[id]/print` stays for saving one by hand
- **Hosting:** frontend on Vercel; backend and scheduler on Railway; Supabase for database, auth and storage. The backend's Vercel project stays deployed as a rollback target

### Monorepo Structure
```
job-hunt-pipeline/
├── frontend/          # Next.js app
├── extension/         # Chrome extension that fills in application forms
├── backend/           # FastAPI
│   ├── app/
│   │   ├── api/v1/    # Route handlers
│   │   ├── models/    # SQLAlchemy ORM models
│   │   ├── schemas/   # Pydantic schemas
│   │   ├── services/  # Business logic (discovery, parsing, dedup, scoring, tailoring, auto_apply, job_alerts)
│   │   ├── workers/   # Async discovery, parsing and scoring functions the API calls
│   │   ├── llm/       # Claude API client + prompt templates
│   │   └── core/      # Config, database, auth middleware
│   └── alembic/       # Database migrations
├── shared/            # Shared constants
└── docker-compose.yml # Local dev Postgres (with pgvector, which old migrations need)
```

## Development

### Local Setup
```bash
# Start Postgres
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
- **Sonnet 5** (`claude-sonnet-5`) for: job parsing, resume parsing, deep reviews, web search, drafting application-form answers (`applying`), resume tailoring and cover letters (`tailoring`)
- **Opus 5** (`claude-opus-5`): nothing today. Tailoring runs on every application now, so it moved to Sonnet — about a fifth of the cost for the same writing. Put a task back on Opus by changing `MODELS`; the server-side fallback is already wired for it
- Model IDs and per-task effort live only in `llm/client.py` (`MODELS`, `EFFORT`). Don't pass `temperature` — current models and SDK 1.x reject it
- Out of credits: the first "credit balance is too low" error pauses every Claude call for 30 minutes (`CREDITS_PAUSE_SECONDS`), then one call tries again, so topping up turns AI back on within half an hour. While paused, calls raise `LLMCreditsExhausted` without reaching the API; the API answers 503 with a plain "try again later" (`PAUSED_MESSAGE`), `/cron/enrich` returns `paused: true` and leaves jobs unread instead of counting them as failed, and the admin page shows a notice (`/api/v1/auth/admin/ai-status`). Callers that build their own requests go through `llm_client.client`, which applies the same pause. The pause lives in the backend process, so it resets on a deploy
- **HARD RULE:** Never fabricate experience, tools, metrics, or employers in tailored content
- **HARD RULE:** Everything written for a user (resume, cover letter, message to a hiring manager, form answers, fit analysis) is plain, simple English that sounds like a person, with no em dashes. The rules live once in `llm/style.py` (`STYLE_RULES`, in every writing prompt) and `plain_english()` cleans the output, since a model still slips
- All generated content validated against candidate's structured profile before showing to user
- Track token usage per call for cost management

### Job Pipeline
Every job flows: Raw → Normalized → Deduplicated → Enriched → Scored → Inbox
- Dedup uses canonical hash (normalized company+title+city+country) + description similarity
- Enrichment: `/api/v1/cron/enrich` reads recent jobs with Haiku (skills, requirements, seniority, salary with its period, sponsorship, `eligible_countries`), then rescores them for every user. The best-scored jobs for any user are read first: an unread job's level and skills are unknown, which keeps its score down. It costs about $0.0045 a job, so it only reads jobs that score at least `ENRICH_MIN_SCORE` (40) for someone, and at most `ENRICH_DAILY_LIMIT` (200) a day. Reading everything burned $10 in four days once; about 70% of unread jobs score under 40 for everyone
- Scoring (`services/scoring/scorer.py` + `matching.py`) is the same for every profession: title vs target roles/interests/recent titles, skills overlap, seniority, industry, remote fit. It must stay fast: a full rescore covers the whole catalog inside 60s
- Scoring versions: `SCORE_VERSION` is what `job_scores` stores (5 since 2026-09-25); `PROPOSED_SCORE_VERSION` is the next one, not live yet. Version 5 counts a part only when both sides know something about it (skills when the job lists 3+, the level when both are known, remote when the user has a preference and the job states its policy, industry when the profile has industries) and compares titles by their specific words (generic role nouns weigh 0.3; text after " @ " is the company). `/ratings/results?compare=2,3,4` measures any known version on a user's ratings. After a switch, the scheduler's `/cron/rescore-outdated` step rescores users with older-version scores, two per run Version 3 gives nothing for what isn't known (a level or remote policy the job doesn't state counts as 0; a part the profile has nothing for is left out and the other weights share its weight) and holds jobs matching neither the user's roles nor their skills at 45, below the inbox's 50
- Rate matches (`/dashboard/rate`, `/api/v1/ratings`, `job_ratings`): users say whether jobs fit them without seeing scores. `services/scoring/evaluation.py` scores the rated jobs live with both versions and compares them with the ratings. Measure a scoring change there before it goes live; to switch, set `SCORE_VERSION` to the proposed version, deploy, then rescore every user (`/api/v1/cron/score-backlog?rescore_all=true`)
- Hard filters (`services/jobs_filter.py`) hide jobs per user: preferred countries, remote preference, remote roles restricted away from the user's home country, no sponsorship where the user needs it, and source-stated salary below the user's minimum. A job that doesn't state a fact is never hidden by it
- Inbox relevance: a job's title matches the user's roles or skills, or its score shows a skill match (`job_scores.skill_score > 0`). Never filter inbox queries on `raw_description`: ~83 MB of text across 12k jobs made each query take ~25s
- Discovery sources keep location-restricted jobs and tag `eligible_countries`; they don't drop them
- `/api/v1/cron/review-top-matches` runs deep reviews on each user's best new matches, capped per user per day
- Freshness: ingest sets `jobs.last_seen_at` whenever a source lists a job again. `/api/v1/cron/expire-stale` expires jobs gone from full company boards (`curated`, unseen 5 days) and jobs older than 45 days that no source has listed for 30 days, then probes a batch of links (`last_checked_at`, 404/410 → expired). Jobs a user applied to or tailored for are never expired; old shortlisted ones are kept
- Users edit their roles and skills on Profile (`/candidates/work-history`, `/candidates/skills`). Roles are kept in date order, current ones first (`_order_work_history`): `seniority_match` reads the first role as the candidate's level. Edits don't rescore; the page offers "Update my matches" (`POST /candidates/rescore`)
- Resume upload doesn't rescore inline (parse + full rescore can exceed 60s); the frontend calls `POST /candidates/rescore` afterwards
- Tailoring runs as part of preparing an application (`prepare_application(tailor=True)`, the default from the API) and on the user's own "Tailor application" button. It writes the resume and cover letter; the message to a hiring manager is written later, from the sent application, not for every job
- Applications attach files the app draws itself (`services/auto_apply/resume_pdf.py`, fpdf2): the tailored resume when the job has one, else the profile's uploaded file, plus a cover letter when the form asks for one. Both are stored under `applications/<user>/<application>-*.pdf` in the resumes bucket and handed to the extension and the sender as short-lived signed links

### Daily email (`services/notifications/`, `/api/v1/notifications`)
- Each morning (first scheduler run at or after `DIGEST_HOUR_UTC`, default 7) `/cron/send-digests` emails every user with `users.email_digest` on who hasn't had today's: the best new inbox jobs since the last email (inbox filters, score 50+, one posting per job, top 5), Apply for me applications that need answers, tailored applications ready in the last 14 days, and follow-ups due. Days with nothing new send nothing. `users.last_digest_sent_at` makes it once a day
- Railway's plan blocks SMTP, so email goes out over HTTPS (`email.py`): `EMAIL_PROVIDER=resend` (`RESEND_API_KEY`, `EMAIL_FROM` on a domain verified with Resend) or `EMAIL_PROVIDER=apps_script` (`EMAIL_RELAY_URL`, `EMAIL_RELAY_SECRET`; a Google Apps Script web app in the sending Gmail account, `backend/scripts/email_relay.gs`, 100 recipients a day). Unset: nothing is sent and the cron step is a no-op
- Profile → Preferences → Daily email: on/off, a preview (rendered, not sent) and a test send. The email's "stop these emails" link is `/notifications/unsubscribe?u=&t=`, an HMAC of the user id keyed on `SUPABASE_JWT_SECRET`; links use `FRONTEND_URL` and `API_PUBLIC_URL` (falls back to `RAILWAY_PUBLIC_DOMAIN`)

### LinkedIn job alerts (`services/job_alerts/`, `/api/v1/job-alerts`)
- Each user runs a Google Apps Script in the Gmail account that gets their LinkedIn job alerts. Profile → Preferences writes it with their key (`frontend/src/lib/linkedin-alert-script.ts`). Every hour it sends new emails from `jobalerts-noreply@linkedin.com` to `POST /job-alerts/linkedin` with `Authorization: Bearer jha_…`. Only the key's SHA-256 is stored (`job_alert_keys`)
- The script strips every link's query string except `trk`: LinkedIn's links carry one-time sign-in codes (`otpToken`, `midToken`). The backend never stores the email, only the jobs read from it
- `linkedin.py` reads the jobs from the email: the job id from each `/jobs/view/<id>` link, the section and position from `trk` (`primary_job_list-0-jobcard_body_1_jobid_…`), then title, "Company · Location (Remote)", salary and labels. Parsing lives in the backend so layout changes don't need every user to update their script
- `ingest.py`: one job row per LinkedIn id for everyone (`linkedin_jobs`); a job the app already has (same link, or same company, title, city and country) is reused and reopened if expired. `job_alert_hits` records per user which jobs their alerts sent; `job_alert_emails` makes a resent email a no-op
- Alert emails have no description. `/cron/job-alert-details` (every scheduler run) looks each new job up once on the company's own job board (`ats_resolver.resolve_ats_url`, then the Greenhouse/Lever/Ashby posting APIs). Free: no LinkedIn pages, Firecrawl or Claude
- Rate matches samples up to 10 alert jobs whatever their score and reports how often the user rates them good. "LinkedIn sent it" doesn't change scores until ratings show it should

### Applications page (`/dashboard/applications`)
- The one place for applying, and the only sidebar entry for it: **Needs you** (applications with questions open, plus resumes written for jobs without an application, from the last 30 days), **Ready to send** (approved), then everything **Sent** (`application_tracking`, grouped by status), and a folded list of stopped applications and older resumes. The sidebar and dashboard count the same things
- `/dashboard/auto-apply` redirects here. `/dashboard/review` still exists for changing a tailored resume's wording, reached from an application; it's no longer in the sidebar
- A job page has one main action: **Apply for me** when the form is on Greenhouse, Lever or Ashby (or **Continue your application**), otherwise **Apply on their site** with a line saying why, plus **Write a resume for this job**. Tailoring isn't a separate button when Apply for me is available, because Apply for me tailors

### Apply for me (`services/auto_apply/`, `/api/v1/auto-apply`)
- Supported: jobs whose `apply_url`/`job_url` is on Greenhouse, Lever or Ashby (`ats.py`). Greenhouse and Ashby publish each job's form as JSON; Lever's is read from its apply page (`forms.py`). All three forms carry invisible bot checks (reCAPTCHA / hCaptcha): never build anything that gets around them
- `prepare_application` reads the form, fills answers from the profile with rules (`answers.py`), then drafts the remaining required questions in one Claude call (`drafting.py`). Every answer records its `source` and whether it's `confirmed`
- Only confirmed answers come from facts: profile and resume, the user's earlier answer to the same question (`saved_answers`, confirmed for 30 days), declining voluntary demographic questions and marketing messages. Suggested and drafted answers always need the user
- The questions every employer asks (start date, relocation, languages, university, how you heard, years of experience, salary) are remembered by what they mean, not how a form words them: `question_key(item, kind)` keys them on the kind for `STANDARD_KINDS`. Company questions stay keyed on the wording, so "Why Anthropic?" never fills in "Why Palantir?"
- Answers that are facts about the person go back to the profile when the user approves (`_remember_on_profile`): phone, location, earliest start, relocation, languages, and work rights per country in `visa_statuses` (a question naming no country is about the job's country). Profile → Preferences → Application answers is the same set, fillable up front; a dismissible prompt asks for them after setup
- Legal agreements, acknowledgements and attestations are never answered for the user, even when required. Work authorization and sponsorship are answered only when `home_country`/`visa_statuses` settle them for the job's country
- Statuses: `needs_you` until every required question is answered and confirmed, then `queued` once the user approves (`PUT /{id}/answers` with `approve`), then `submitted` once sent
- The server never sends applications. The Chrome extension (`extension/`) fills in the company's form in the user's own browser and the user presses Submit: the app page gets `GET /{id}/fill` (answers, a 10-minute signed resume link, `sent_url` + `sent_token`) and posts it to the extension's content script on the app (`app-bridge.js`, protocol in `frontend/src/lib/extension.ts`). `background.js` downloads the resume and opens the form in a new tab; `form-bridge.js` hands the answers to `fill.js`, which runs in the page's own world because Greenhouse's react-select dropdowns only take a choice through the component (`selectOption` found from the input's React fiber). Text goes in through the native value setter plus input/change events; files through `DataTransfer`. Greenhouse is server-rendered: wait for React to take over before touching it, or React redraws the page and drops the resume
- After the user presses Submit, `form-bridge.js` watches for the confirmation page (`/confirmation`, `/thanks`) or a thank-you message with the form gone, and posts `sent_token` to `POST /{id}/sent-by-extension` (no login; an HMAC of the application id keyed on `SUPABASE_JWT_SECRET`, like the email's unsubscribe link). `POST /{id}/sent` is the app's "I sent it myself". Both mark it `submitted` and track the job as applied (`services/tracking/applied.py`)
- Follow up (`services/outreach/follow_up.py`, `POST /auto-apply/{id}/follow-up`): once an application is `submitted`, the user can ask for a message to a person. The contact comes from the existing job lookup (`POST /jobs/{id}/find-contact`, Claude web search, cached per job); the message is drafted from the job, the user's facts and the tailored summary, then kept on `auto_applications.follow_up`. Both only run when the user presses the button, and the app never sends the message: LinkedIn doesn't allow it, so the user copies it
- The install page (`/dashboard/extension`) serves `frontend/public/job-hunt-extension.zip`. After changing anything in `extension/`, run `extension/package.sh` and commit the zip. The manifest's `host_permissions` must include the backend's public URL, and its content script matches the app's URLs

### Testing
```bash
cd backend
pytest tests/unit/
# Integration tests need a disposable Postgres with the pgvector extension
# (an old migration creates vector columns), migrated to head, whose
# database name contains "test". They TRUNCATE tables.
TEST_DATABASE_URL=postgresql://user@localhost:5432/jobhunt_test pytest tests/integration/
```

## Environment Variables
See `backend/.env.example` and `frontend/.env.example` for all required variables.

## Important Notes
- Public signups are DISABLED in Supabase — users are added via admin invite only
- In production, connect to Supabase PostgreSQL via Transaction Mode (port 6543). `DB_POOL_SIZE` picks the connection handling (`core/database.py`): `0` opens one per request (Vercel), above `0` keeps connections open (Railway)
- All tailored application materials require human approval before use

## Deployment (Vercel)

Both frontend and backend deploy as **separate Vercel projects** pointing at the same GitHub repo.

### Backend project
- **Root directory**: `backend`
- **Region**: `dub1` (Dublin, set in `backend/vercel.json`), next to the Supabase database in AWS eu-west-1. Keep them together: every request opens a fresh database connection
- **Framework preset**: Other (Vercel auto-detects Python via `vercel.json`)
- **Required env vars**: `DATABASE_URL` (Supabase pooler, port 6543), `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SUPABASE_JWT_SECRET`, `ANTHROPIC_API_KEY`, `FIRECRAWL_API_KEY`, `JSEARCH_RAPIDAPI_KEY`, `CORS_ORIGINS`, `CRON_SECRET`
- **No cron jobs**: scheduled work runs on Railway (below). The Vercel backend stays deployed only as a rollback target

### Backend on Railway
The website (`NEXT_PUBLIC_API_URL`) uses the Railway backend: no time limit on requests, and room for the auto-apply worker. To roll back, set it back to `https://backend-nakel0s-projects.vercel.app`, redeploy the frontend, and restore the crons in `backend/vercel.json` from git history.
- **Project** `job-hunt-pipeline`, service `backend`, https://backend-production-7e805.up.railway.app
- **Build**: `backend/Dockerfile` (uvicorn on `$PORT`, two processes via `WEB_CONCURRENCY`)
- **Service settings** live on Railway, not in the repo (Railway ignores `railway.json` now): region EU West / Amsterdam (`europe-west4-drams3a`), health check `/health`, restart on failure up to 5 times
- **Env vars**: the same as the Vercel backend, plus `DB_POOL_SIZE=5`
- **Deploys** automatically from GitHub `main` (root directory `/backend`, watch paths `/backend/**`). `cd backend && railway up --service backend` deploys the local checkout instead
- Cron endpoints refuse every request until `CRON_SECRET` is set

### Scheduler on Railway
Service `scheduler` in the same project is a Railway cron service: every 30 minutes (`*/30 * * * *`) it runs `python scripts/scheduled_tasks.py` from the backend image and exits. That script calls the backend's cron endpoints: discovery at 06:00 (`discover-fast`) and 06:30 UTC (`discover-remote`), and on every run `enrich`, `job-alert-details`, `expire-stale`, `send-digests` and, when `REVIEWS_PER_USER_PER_DAY` > 0, `review-top-matches`.
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
- The Vercel rollback backend stops every request after 60 seconds; Railway has no such limit.
