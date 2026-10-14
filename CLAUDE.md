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
- Out of credits: the first "credit balance is too low" error pauses every Claude call for 30 minutes (`CREDITS_PAUSE_SECONDS`), then one call tries again, so topping up turns AI back on within half an hour. While paused, calls raise `LLMCreditsExhausted` without reaching the API; the API answers 503 with a plain "try again later" (`PAUSED_MESSAGE`), `/cron/enrich` returns `paused: true` and leaves jobs unread instead of counting them as failed, and the admin page shows a notice (`/api/v1/auth/admin/ai-status`). Callers that build their own requests go through `llm_client.client`, which applies the same pause. The backend runs several worker processes, so the pause is kept in a small file in the container's temp folder (`PAUSE_FILE`) as well as in memory: every worker and the admin notice agree, and a deploy clears it. `end_credits_pause()` turns AI back on at once. Tests get their own pause file (tests/conftest.py)
- **HARD RULE:** Never fabricate experience, tools, metrics, or employers in tailored content
- **HARD RULE:** Everything written for a user (resume, cover letter, message to a hiring manager, form answers, fit analysis) is plain, simple English that sounds like a person, with no em dashes. The rules live once in `llm/style.py` (`STYLE_RULES`, in every writing prompt) and `plain_english()` cleans the output, since a model still slips
- **HARD RULE:** An application is never "ready to send" until everything it sends passes the writing check (`writing_problems` in `llm/style.py`: long dashes, words people don't say out loud, stiff openings, sentences over 40 words). That includes answers the user typed or pasted (`answers.py`: written answers of 8+ words), the tailored resume's summary and bullets and the cover letter when the form asks for one (`services/auto_apply/writing.py`). Approving is refused while anything is flagged. The user can press **Rewrite in plain English** (`/auto-apply/{id}/rewrite`): it rewrites, reads through and fixes up to `REWRITE_ROUNDS` (3) times, then saves the result unapproved in one press, so pressing again never brings a fresh set of problems. Or they keep flagged words (`/keep-wording`), but long dashes always come out
- **Read-through:** besides those mechanical checks, the model reads each written answer, the resume (summary and bullets) and the cover letter like a careful friend (`read_through` in `llm/style.py`, task `review`): jargon, run-on sentences, stiff or salesy phrasing, wording lifted from the job ad. What it finds is kept with the text and its fingerprint (on the answer, or in the tailored application's `validation_notes["read_through"]`), so it only runs again when the words change. Text it couldn't read shows "The app hasn't read this through yet" and approving is refused. What the app writes itself (resume, cover letter, drafted answers) is then fixed (`revise_plainly`: same facts, nothing added, same number of lines) and read again, so the user only sees what's left (`make_documents_plain` in `writing.py`, `read_answers_through` in `prepare.py`). The user's own answers are only ever flagged, never changed. Only findings the reviewer marks `serious` count: a reviewer always finds something, and taste isn't a reason to wait. Documents can be kept as they are too (`/keep-document-wording`, never with long dashes)
- Long dashes are rewritten by the model (`without_dashes`), not swapped for commas: that made run-on sentences. `plain_english` is the fallback: a single dash ends the sentence, a pair becomes commas
- Preparing an application takes up the live posting (Greenhouse sends it with the form): a changed title or description updates the job, rescores it, marks it for the job reader again, and writes the resume and cover letter again (`_take_up_posting` in `prepare.py`)
- All generated content validated against candidate's structured profile before showing to user
- Spending: every Claude call is counted per hour, task and model in `ai_usage_hours` (`services/ai_credit.py`, from `_count_call` in `llm/client.py`), priced from `PRICES_PER_MILLION` (list prices, update them when Anthropic's change) plus $0.01 per web search. Callers that build their own requests pass `usage_task=` to `llm_client.client.messages.create` so they're counted too (web job search, apply-link lookup, contact lookup, translation). Counting never fails a call. The Anthropic account can be shared with other products, so its balance says nothing about Job Hunt: Job Hunt has a monthly budget instead (`ai_monthly_budget_usd`, $15 to start; the admin changes it on the admin page, `PUT /auth/admin/ai-budget`, kept in the admin's `users.preferences`). `/auth/admin/ai-credit` shows spending by day and task and this month against the budget; `/auth/admin/ai-status` warns admins on every page (`AiCreditBanner`) when the AI is paused, 80% of the budget is used, or the month is heading over it. At the budget, background AI work waits for the 1st of the month (`/cron/enrich`, `/cron/review-top-matches`, and automatic preparing from $0.50 before it); what a user asks for still runs. `POST /auth/admin/ai-on` ends the credit pause at once after a top-up. `ai_credit_balances` is no longer written. Tests keep counts in a list (`ai_calls_counted` in tests/conftest.py)
- Startup: `app/core/warmup.py` runs in the app's lifespan before Uvicorn opens the port (Railway waits for `/health`): loads every module, opens the database pool's connections, fetches the login keys, draws a PDF and creates the AI client, each step timed and allowed to fail. Without it the first page after a deploy waited ~27s per request. Token checks run in a thread (`deps.get_current_user`): PyJWKClient fetches keys with a blocking call
- Logs: `app/core/logging.py` sends the app's own messages to stdout at `LOG_LEVEL` (INFO), which is what Railway shows. Before 2026-09-25 nothing but uvicorn's lines reached the logs. httpx and friends stay at WARNING because they log full URLs, signed links included. Use `logger.debug` for anything logged once per job

### Job Pipeline
Every job flows: Raw → Normalized → Deduplicated → Enriched → Scored → Inbox
- Dedup uses canonical hash (normalized company+title+city+country) + description similarity
- Enrichment: `/api/v1/cron/enrich` reads recent jobs with Haiku (skills, requirements, seniority, salary with its period, sponsorship, `eligible_countries`), then rescores them for every user. The best-scored jobs for any user are read first: an unread job's level and skills are unknown, which keeps its score down. It costs about $0.0045 a job, so it only reads jobs that score at least `ENRICH_MIN_SCORE` (40) for someone, and at most `ENRICH_DAILY_LIMIT` (200) a day. Reading everything burned $10 in four days once; about 70% of unread jobs score under 40 for everyone
- Scoring (`services/scoring/scorer.py` + `matching.py`) is the same for every profession: title vs target roles/interests/recent titles, skills overlap, seniority, industry, remote fit. It must stay fast: a full rescore covers the whole catalog inside 60s
- Scoring versions: `SCORE_VERSION` is what `job_scores` stores (5 since 2026-09-25); `PROPOSED_SCORE_VERSION` is the next one, not live yet. Version 5 counts a part only when both sides know something about it (skills when the job lists 3+, the level when both are known, remote when the user has a preference and the job states its policy, industry when the profile has industries) and compares titles by their specific words (generic role nouns weigh 0.3; text after " @ " is the company). `/ratings/results?compare=2,3,4` measures any known version on a user's ratings. After a switch, the scheduler's `/cron/rescore-outdated` step rescores users with older-version scores, two per run Version 3 gives nothing for what isn't known (a level or remote policy the job doesn't state counts as 0; a part the profile has nothing for is left out and the other weights share its weight) and holds jobs matching neither the user's roles nor their skills at 45, below the inbox's 50
- Rate matches (`/dashboard/rate`, `/api/v1/ratings`, `job_ratings`): users say whether jobs fit them without seeing scores. `services/scoring/evaluation.py` scores the rated jobs live with both versions and compares them with the ratings. Measure a scoring change there before it goes live; to switch, set `SCORE_VERSION` to the proposed version, deploy, then rescore every user (`/api/v1/cron/score-backlog?rescore_all=true`)
- Hard filters (`services/jobs_filter.py`) hide jobs per user: preferred countries, remote preference, remote roles restricted away from the user's home country, no sponsorship where the user needs it, and source-stated salary below the user's minimum. A job that doesn't state a fact is never hidden by it
- Inbox relevance: a job's title matches the user's roles or skills, or its score shows a skill match (`job_scores.skill_score > 0`). Never filter inbox queries on `raw_description`: ~83 MB of text across 12k jobs made each query take ~25s
- Job cards say how fresh a job is (`frontend/src/lib/freshness.ts`): "Posted" or "Found" N ago, from the posting date when the source gives one earlier than when the app found it, plus "still listed today/this week" for jobs 2+ weeks old that a source still lists. The dates are when the app found a job, so an old one that's still listed would otherwise look stale
- Jobs a user has worked on (tailored, tracked, Apply for me, saved): once the app last saw one listed more than 21 days ago the API adds `closed_note` ("This job may have closed...", or "This job has closed." once expired; `services/job_freshness.py`). A job never listed again counts from when it was found. The link checker looks at these first, once a day each, and settles them where it can (see Freshness). The Applications page shows the note only where it changes what the user does: applications being prepared, resumes to check, and approved ones not yet sent. Never on sent ones: the company can still reply, and they move to No reply after 30 days. The API also returns `job.closed`; a resume whose job closed moves to Closed
- Company boards (curated, `curated_companies.json`, 218 companies since 2026-10-11, 79 of them AI and automation employers checked live that day): every listing on a board that answered (16.7k on 2026-10-11) is passed to `services/maintenance/board_listings.py`, which marks jobs we have as still listed, takes up new titles (companies rename jobs) and reopens jobs it had closed, and collects which listings the app already has (`known`). New jobs are then picked by `pick_new_jobs`: only ones the app doesn't have and whose title matches some user's target roles, search keywords or skills (`title_matcher`, whole words, ~7% of listings), up to 30 per company, companies taking turns, 500 in all. Without the title match it added 500 mostly irrelevant jobs a day, which would fill the free database (500 MB, 270 MB used on 2026-10-11, ~9.5 KB a job) in about five weeks. Before 2026-10-11 it took each board's 30 newest in list order and stopped at 500, so the first ~17 companies filled it every day, mostly with jobs already known, and the rest never added one. The discovery step gets 150s per source (`PER_SOURCE_BUDGET_SECONDS`)
- The LinkedIn alert lookup (`ats_resolver._slug_candidates`) only tries a company's first word alone when the other words are generic ("Wayve Technologies" → `wayve`), since "parker" or "blue" are other companies' boards
- Discovery sources keep location-restricted jobs and tag `eligible_countries`; they don't drop them
- `/api/v1/cron/review-top-matches` runs deep reviews on each user's best new matches, capped per user per day
- Database size (Supabase free plan, 500 MB; 270 MB on 2026-10-11, 140 MB of it job text): `/cron/expire-stale` also empties the stored text (`raw_description`, `raw_description_en`, `raw_content`) of up to 2000 jobs a run (`services/maintenance/trim_jobs.py`): closed (expired or duplicate) more than 30 days, or older than 45 days and never scored 40 for anyone. Never a job anyone applied to, started, tailored, saved or dismissed, rated or looked up a contact for. Rows stay, so jobs aren't added twice; freed space is reused, and the file only shrinks after a `VACUUM FULL`
- Freshness: ingest sets `jobs.last_seen_at` whenever a source lists a job again. `/api/v1/cron/expire-stale` expires jobs gone from full company boards (`curated`, unseen 5 days; not ones someone worked on) and jobs older than 45 days that no source has listed for 30 days (worked-on ones too, saved or not, except on Greenhouse, Lever or Ashby: `HIRING_SYSTEM_URL` in `job_expiry.py`), then runs the link checker (`url_verifier.py`, 40 a run, `last_checked_at`): worked-on jobs unlisted for 21 days first, then the least recently checked. Greenhouse, Lever and Ashby jobs are asked through `fetch_form`, which says for certain: closed → expired, open → `last_seen_at` = now (the note goes). Other links: 404/410 → expired; a page that loads proves nothing (Greenhouse sends closed jobs to the company's board). Expiring never deletes a user's records: sent applications stay in Sent, unsent ones move to Closed (`services/tracking/quiet.py`). A job a source or board lists again is reopened. On 2026-10-11 Palantir, sent that day, was unlisted for 26 days: "not listed" alone is not proof
- Users edit their roles and skills on Profile (`/candidates/work-history`, `/candidates/skills`). Roles are kept in date order, current ones first (`_order_work_history`): `seniority_match` reads the first role as the candidate's level. Edits don't rescore; the page offers "Update my matches" (`POST /candidates/rescore`)
- Resume upload doesn't rescore inline (parse + full rescore can exceed 60s); the frontend calls `POST /candidates/rescore` afterwards
- Tailoring runs as part of preparing an application (`prepare_application(tailor=True)`, the default from the API) and on the user's own "Tailor application" button. It writes the resume and cover letter; the message to a hiring manager is written later, from the sent application, not for every job
- Applications attach files the app draws itself (`services/auto_apply/resume_pdf.py`, fpdf2): the tailored resume when the job has one, else the profile's uploaded file, plus a cover letter when the form asks for one. Both are stored under `applications/<user>/<application>-*.pdf` in the resumes bucket and handed to the extension and the sender as short-lived signed links

### Daily email (`services/notifications/`, `/api/v1/notifications`)
- Each morning (first scheduler run at or after `DIGEST_HOUR_UTC`, default 7) `/cron/send-digests` emails every user with `users.email_digest` on who hasn't had today's: the best new inbox jobs since the last email (inbox filters, score 50+, one posting per job, top 5), Apply for me applications that need answers, tailored applications ready in the last 14 days, and follow-ups due. Days with nothing new send nothing. `users.last_digest_sent_at` makes it once a day
- Railway's plan blocks SMTP, so email goes out over HTTPS (`email.py`): `EMAIL_PROVIDER=resend` (`RESEND_API_KEY`, `EMAIL_FROM` on a domain verified with Resend) or `EMAIL_PROVIDER=apps_script` (`EMAIL_RELAY_URL`, `EMAIL_RELAY_SECRET`; a Google Apps Script web app in the sending Gmail account, `backend/scripts/email_relay.gs`, 100 recipients a day). Unset (how production runs since 2026-10-11): the admin's LinkedIn alert script sends it. Every 10 minutes it asks `POST /job-alerts/outbox` for due emails (`services/notifications/outbox.py`: requested test emails, then today's emails; days with nothing new are marked done), sends them from its Gmail as "Job Hunt" (`GmailApp.sendEmail`), and reports `POST /job-alerts/outbox/sent`. Only an admin's key gets any. Test emails are queued (`users.preferences["digest_test_requested_at"]`) and go on the next run
- Who gets it: admins only until an admin turns on "Send it to every user" on Preferences → Daily email (`users.preferences["digest_everyone"]`, `PUT /notifications/settings {everyone}`, admins only), so the admin can try it first. `recipients_due` applies this for every sender
- Content: top matches list jobs the app has a description for first (`HAS_DESCRIPTION`, `pg_column_size`, never reading the text), so title-only LinkedIn alert jobs don't lead; follow-ups more than 14 days overdue are left out; no long dashes
- Profile → Preferences → Daily email: on/off, a preview (rendered, not sent) and a test send. The email's "stop these emails" link is `/notifications/unsubscribe?u=&t=`, an HMAC of the user id keyed on `SUPABASE_JWT_SECRET`; links use `FRONTEND_URL` and `API_PUBLIC_URL` (falls back to `RAILWAY_PUBLIC_DOMAIN`)

### LinkedIn job alerts (`services/job_alerts/`, `/api/v1/job-alerts`)
- A Google Apps Script in a Gmail account that gets LinkedIn job alerts. Profile → Preferences writes it with the user's key (`frontend/src/lib/linkedin-alert-script.ts`). Every 10 minutes it sends new emails from `jobalerts-noreply@linkedin.com` to `POST /job-alerts/linkedin` with `Authorization: Bearer jha_…`. Only the key's SHA-256 is stored (`job_alert_keys`)
- Shared inbox (`services/job_alerts/forwarding.py`): an admin's script also reports its inbox (`users.preferences["alert_inbox"]`) and sends each email's delivery headers (`recipients`) and Gmail's forwarding confirmation emails (`kind: "confirmation"`). Everyone else forwards their alerts there with a Gmail filter, to a personal plus address (`inbox+<code>@gmail.com`, `GET /job-alerts/forwarding`, code in `users.preferences["alert_forward_code"]`). The backend routes each email to the user whose code it was delivered to, and shows Gmail's confirmation code to that user. Only an admin's key routes to other users. To move the inbox later: forward the old account to the new one and run the script there
- The script strips every link's query string except `trk`: LinkedIn's links carry one-time sign-in codes (`otpToken`, `midToken`). The backend never stores the email, only the jobs read from it
- `linkedin.py` reads the jobs from the email: the job id from each `/jobs/view/<id>` link, the section and position from `trk` (`primary_job_list-0-jobcard_body_1_jobid_…`), then title, "Company · Location (Remote)", salary and labels. Parsing lives in the backend so layout changes don't need every user to update their script
- `ingest.py`: one job row per LinkedIn id for everyone (`linkedin_jobs`); a job the app already has (same link, or same company, title, city and country) is reused and reopened if expired. `job_alert_hits` records per user which jobs their alerts sent; `job_alert_emails` makes a resent email a no-op
- Alert emails have no description. `/cron/job-alert-details` (every scheduler run) looks each new job up once on the company's own job board (`ats_resolver.resolve_ats_url`, then the Greenhouse/Lever/Ashby posting APIs). Free: no LinkedIn pages, Firecrawl or Claude
- Rate matches samples up to 10 alert jobs whatever their score and reports how often the user rates them good. "LinkedIn sent it" doesn't change scores until ratings show it should

### Applications page (`/dashboard/applications`)
- The one place for applying, and the only sidebar entry for it: **Needs you** (applications with questions open, plus resumes written for jobs without an application, from the last 30 days), **Ready to send** (approved), then everything **Sent** (`application_tracking`, grouped by status), and a folded list of stopped applications and older resumes. The sidebar and dashboard count the same things
- Old applications close by themselves (`services/tracking/quiet.py`, run by `/cron/expire-stale`): sent applications (`applied`, `follow_up_due`) with no reply after `QUIET_DAYS` (30) move to `ghosted`, shown as **No reply** with the closed ones, and the user can move them back. Unsent applications (`needs_you`, `queued`) whose job has expired are `cancelled` with `JOB_CLOSED`, so they land in the stopped list; approved tracking rows (resume approved, never marked applied) on a closed job are `archived` ("I applied" on the job page brings one back). Sent applications missing a follow-up date get one a week after sending. Cards in Closed show no follow-up date
- Follow-up date: 7 days after applying, both when the user marks a job applied and when the app or extension sends it (`FOLLOW_UP_DAYS` in `services/tracking/applied.py`)
- `/dashboard/auto-apply` redirects here. `/dashboard/review` still exists for changing a tailored resume's wording, reached from an application; it's no longer in the sidebar
- A job page has one main action: **Apply for me** when the form is on Greenhouse, Lever or Ashby (or **Continue your application**), otherwise **Apply on their site** with a line saying why, plus **Write a resume for this job**. Tailoring isn't a separate button when Apply for me is available, because Apply for me tailors

### Apply for me (`services/auto_apply/`, `/api/v1/auto-apply`)
- **Send it for me:** `POST /auto-apply/{id}/send` (`practice` fills in without sending) records a request on `result["request"]`. The Railway `sender` service runs every 5 minutes (cron) and `run_requested` in `sender.py` claims each one (moves it to `result["running"]`; a real send also goes to `submitting`), runs the browser, and keeps the outcome and a screenshot in `result["practice"]` / `result["send"]`. A form that asks for a person, or anything short of a confirmation, leaves it approved with a plain `error`; never work around bot checks. Runs that stop halfway are let go after 20 minutes. The extension stays as the backup way to send
- The sender finds Submit by what it says (`get_by_role("button", name=SUBMIT_LABEL)`), never by its place among the visible buttons: that list changes as Greenhouse's page scrolls, so the button never held still. It hides the filler's `<job-hunt-panel>` (it covered Greenhouse's Submit button) and checks the button can be pressed (`click(trial=True)`) before pressing; a practice run goes as far as that check, so it catches what would stop a real send
- Forms that email a code (`services/auto_apply/email_codes.py`): some Greenhouse forms, after Submit, email the applicant an 8-character code "to confirm you're a human" and only send once it's typed. That's a check that a person is applying: the app never fetches or types the code. The sender spots the step (`_asks_for_email_code`), stops with status `email_code` and a plain message naming the company. Boards that do this (`KNOWN_BOARDS`, seeded with Anthropic from 2026-10-04, plus any board a send has met) get `sending.from_browser_only`: real sends are refused (practice runs still allowed) and the site shows "Send from your browser" with the extension steps. The extension watches for 10 minutes after each Submit press, so the second press after the code is caught
- A practice run also rehearses Submit (`_rehearse_submit`): the browser goes offline and every request is refused (service workers blocked), then Submit is pressed so the form checks each answer and nothing can leave. Answers the form turns down are read from `aria-invalid="true"` (`FORM_ERRORS`) and named in the outcome (`form_rejected`, practice or real); the picture is of the filled-in form, or of the errors. On 2026-09-29 the first real send was turned down this way: `fill.js` picked Greenhouse's dropdowns in one go and each pick overwrote the one before in Greenhouse's React state, so the boxes showed answers the form didn't have. It now waits 150ms after each answer
- Job board listings: Arbeitnow's Apply button is a plain redirect (`<job page>/apply`) to the company's own form, about 78% of the time on Ashby, Greenhouse or Lever, and most inbox jobs come from Arbeitnow. `apply_links.py` reads that redirect into `jobs.apply_url` (one request, no AI): when preparing, the first time a job page is opened, and in bulk on each scheduler run (`/cron/resolve-apply-links`, best matches first). A listing that leads nowhere keeps its own URL as `apply_url`, which marks it checked. Forms on other systems (Join, Personio, Recruitee, Workday...) are named in the unsupported message (`hiring_system_name`). No live job linked to Workday on 2026-09-25
- Supported: jobs whose `apply_url`/`job_url` is on Greenhouse, Lever or Ashby (`ats.py`). Greenhouse and Ashby publish each job's form as JSON; Lever's is read from its apply page (`forms.py`). All three forms carry invisible bot checks (reCAPTCHA / hCaptcha): never build anything that gets around them
- `prepare_application` reads the form, fills answers from the profile with rules (`answers.py`), then drafts the remaining required questions in one Claude call (`drafting.py`). Every answer records its `source` and whether it's `confirmed`
- While the AI is paused, preparing waits: the application sits in `preparing` with `WAITING_FOR_AI` as its `error` (also when the credit runs out part way through), and `/cron/prepare-applications` finishes it once the AI is back. Applications already in `needs_you` or `queued` are left as they are
- **The app prepares applications by itself** (`services/auto_apply/auto_prepare.py`, `/cron/prepare-applications` on every scheduler run, 3 at most per run): users choose 0 to 5 a day on the Applications page (`users.preferences["auto_prepare_per_day"]`, `GET/PUT /auto-apply/settings`, off by default). It picks their best new matches: inbox filters, score 70+, listed in the last 7 days, on a Greenhouse, Lever or Ashby form, not dismissed, tracked or already started, one per company in 30 days. They're marked `result["prepared_by"] = "app"` (the API's `prepared_by`), land in Needs you as "Picked for you by the app", and are never sent without the user. It stops when less than `RESERVE_USD` ($0.50) of the month's AI budget is left. About $0.15 each
- "Why this company/role?" is drafted from the posting and the user's real work (never feelings or a history with the company). A written company question the app still left empty gets **Write a first go** (`POST /auto-apply/{id}/first-go`, `write_first_go` in `prepare.py`): one question, drafted with `first_go=True` so the model doesn't answer null, read through and fixed like any draft, saved unconfirmed. Never over the user's own answer
- Links on the profile (LinkedIn, GitHub, portfolio; GitHub has its own box on Profile) fill matching form fields. Saving a link also fills it into the user's unsent applications where the field is empty (`fill_profile_links`, from `PUT /candidates/profile`). The user's proudest project (Preferences → Application answers, `users.preferences["proudest_project"]`, saved through `PUT /auto-apply/settings`) goes into the drafting facts, so a "favourite or proudest project" question is about that one
- Only confirmed answers come from facts: profile and resume, the user's earlier answer to the same question (`saved_answers`, confirmed for 30 days), declining voluntary demographic questions and marketing messages. Suggested and drafted answers always need the user
- The questions every employer asks (start date, relocation, languages, university, how you heard, years of experience, salary) are remembered by what they mean, not how a form words them: `question_key(item, kind)` keys them on the kind for `STANDARD_KINDS`. Company questions stay keyed on the wording, so "Why Anthropic?" never fills in "Why Palantir?"
- Answers that are facts about the person go back to the profile when the user approves (`_remember_on_profile`): phone, location, earliest start, relocation, languages, and work rights per country in `visa_statuses` (a question naming no country is about the job's country). Profile → Preferences → Application answers is the same set, fillable up front; a dismissible prompt asks for them after setup
- Legal agreements, acknowledgements and attestations are never answered for the user, even when required. Work authorization and sponsorship are answered only when `home_country`/`visa_statuses` settle them for the job's country
- Statuses: `needs_you` until every required question is answered and confirmed, then `queued` once the user approves (`PUT /{id}/answers` with `approve`), then `submitted` once sent
- The server never sends applications. The Chrome extension (`extension/`) fills in the company's form in the user's own browser and the user presses Submit: the app page gets `GET /{id}/fill` (answers, a 10-minute signed resume link, `sent_url` + `sent_token`). The app's own Open buttons for the tailored resume and cover letter fetch a fresh signed link from `GET /{id}/documents` when pressed (`openDocument` on the application page), because a link kept on the page goes stale after 10 minutes (Supabase answers `InvalidJWT`) and posts it to the extension's content script on the app (`app-bridge.js`, protocol in `frontend/src/lib/extension.ts`). `background.js` downloads the resume and opens the form in a new tab; `form-bridge.js` hands the answers to `fill.js`, which runs in the page's own world because Greenhouse's react-select dropdowns only take a choice through the component (`selectOption` found from the input's React fiber). Text goes in through the native value setter plus input/change events; files through `DataTransfer`. Greenhouse is server-rendered: wait for React to take over before touching it, or React redraws the page and drops the resume
- After the user presses Submit, `form-bridge.js` watches for the confirmation page (`/confirmation`, `/thanks`) or a thank-you message with the form gone, and posts `sent_token` to `POST /{id}/sent-by-extension` (no login; an HMAC of the application id keyed on `SUPABASE_JWT_SECRET`, like the email's unsubscribe link). `POST /{id}/sent` is the app's "I sent it myself". Both mark it `submitted` and track the job as applied (`services/tracking/applied.py`)
- **Message someone after applying** (`services/outreach/message.py`, `/api/v1/outreach/{job_id}`, `components/message-step.tsx`): once an application is sent (tracking `applied` or `follow_up_due`, whether the app, the extension or "I applied" sent it), the application page (top) and the job page (`#message`) show "Next: message someone at X". `POST /prepare` finds the person (`find_contact`: `contact_finder.py`, Claude web search, hiring manager then head of the team then recruiter, kept on `job_contacts` for everyone; about 10 to 15 cents) and writes a note from the user's real work (`OUTREACH_PROMPT` + `NOTE_RULES`: says they just applied, never says an app wrote or sent anything, 300 characters max for a LinkedIn connection note), checked like answers (`writing_problems`, the length, `read_through`, up to 3 fixes). No one found still gets a note, with a LinkedIn people search. The page writes it by itself only for applications sent in the last `AUTO_DAYS` (7), once per visit; older ones wait for the button. Opening again costs nothing; "Look for someone else" searches again. One `outreach_logs` row per user and job (`drafted`, `sent`, `skipped`); `PUT` saves edits (dashes taken out) or marks it sent, skipped, or not sent after all. The app never sends anything on LinkedIn: the user copies the note, presses Connect and Add a note. LinkedIn jobs point to "Meet the hiring team" first. The tracking list returns `message`; sent cards on Applications show "Message someone" or "Messaged"; the daily email's follow-ups link to `#message` and say when no one was written to. Replaced the old Follow up section (`auto_applications.follow_up` is no longer used)
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
Service `scheduler` in the same project is a Railway cron service: every 30 minutes (`*/30 * * * *`) it runs `python scripts/scheduled_tasks.py` from the backend image and exits. That script calls the backend's cron endpoints: discovery at 06:00 (`discover-fast`) and 06:30 UTC (`discover-remote`), and on every run `enrich`, `resolve-apply-links`, `job-alert-details`, `expire-stale`, `send-digests`, `prepare-applications`, `rescore-outdated` and, when `REVIEWS_PER_USER_PER_DAY` > 0, `review-top-matches`.
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
