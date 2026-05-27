from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select

from app.api.deps import CurrentUser, AdminUser, DbSession
from app.models.user import User
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


class InviteRequest(BaseModel):
    email: EmailStr


class UpdateMeRequest(BaseModel):
    name: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str

    model_config = {"from_attributes": True}


@router.get("/me", response_model=UserResponse)
async def get_current_user(user: CurrentUser, db: DbSession):
    """Get the current authenticated user."""
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
    )


@router.patch("/me", response_model=UserResponse)
async def update_me(request: UpdateMeRequest, user: CurrentUser, db: DbSession):
    """Update the current user's display name.

    Used by the Profile page so the dashboard can greet "Good morning, Olalekan"
    instead of falling back to the email local-part. We trim whitespace and
    enforce a minimum length so a blank submission can't wipe the name."""
    name = (request.name or "").strip()
    if len(name) < 1:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Name too long (max 100 chars)")
    user.name = name
    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        role=user.role,
    )


def _build_supabase_client():
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_service_key)


def _resolve_redirect_to() -> str | None:
    frontend = (settings.frontend_url
                or (settings.cors_origin_list[0] if settings.cors_origin_list else "")
                ).rstrip("/")
    return f"{frontend}/auth/callback" if frontend else None


def _extract_action_link(result) -> str | None:
    properties = getattr(result, "properties", None) or {}
    if isinstance(properties, dict):
        return properties.get("action_link")
    return getattr(properties, "action_link", None)


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite_user(request: InviteRequest, admin: AdminUser, db: DbSession):
    """Invite a NEW user by email (admin only).

    Refuses to operate on existing users. The admin should use
    /resend-magic-link instead for users that already have a row in
    auth.users — that's the right tool for 'I lost my link' or
    'the previous one expired'.

    For brand-new users:
      1. Calls Supabase's invite_user_by_email which creates the
         auth.users row AND sends a real email through Supabase's
         mailer.
      2. The link uses implicit/hash tokens (because the request
         carried no code_challenge), so /auth/callback can complete
         the session via the new POST /auth/set-session route.
    """
    supabase = _build_supabase_client()
    redirect_to = _resolve_redirect_to()
    email = request.email.strip().lower()

    # Existence check: list users matching this email and refuse if any
    # row already exists. We can't trust a single "filter" query (that
    # admin endpoint behaves inconsistently), so we list everyone and
    # match locally.
    try:
        response = supabase.auth.admin.list_users()
        # supabase-py returns a list directly OR an object with .users
        existing_users = response if isinstance(response, list) else (
            getattr(response, "users", None) or []
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't query existing users: {e}",
        )
    if any((u.email or "").lower() == email for u in existing_users):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{email} already has an account. "
                f"Use 'Resend magic link' on the user row instead."
            ),
        )

    options = {"redirect_to": redirect_to} if redirect_to else None
    try:
        kwargs: dict = {}
        if options:
            kwargs["options"] = options
        supabase.auth.admin.invite_user_by_email(email, **kwargs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to send invite: {e}",
        )
    return {
        "status": "invited",
        "email": email,
        "redirect_to": redirect_to,
        "magic_link": None,
        "message": "Invite email sent. Tap the link in the email to land on the dashboard.",
    }


@router.post("/resend-magic-link", status_code=status.HTTP_200_OK)
async def resend_magic_link(request: InviteRequest, admin: AdminUser, db: DbSession):
    """Mint a fresh magic link for an existing user (admin only).

    Used when a user has been invited before but never signed in
    successfully (or their previous link expired/was consumed). Returns
    the URL — does NOT send an email — because Supabase's invite_user
    refuses to re-send and admin.generate_link is the only way to mint
    a fresh single-use token. The admin pastes it into WhatsApp/SMS/
    email out-of-band.
    """
    supabase = _build_supabase_client()
    redirect_to = _resolve_redirect_to()
    email = request.email.strip().lower()

    options = {"redirect_to": redirect_to} if redirect_to else None
    try:
        link_kwargs: dict = {"type": "magiclink", "email": email}
        if options:
            link_kwargs["options"] = options
        result = supabase.auth.admin.generate_link(link_kwargs)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Couldn't mint magic link: {e}",
        )

    action_link = _extract_action_link(result)
    if not action_link:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Supabase returned no action_link",
        )
    return {
        "status": "magic_link_minted",
        "email": email,
        "redirect_to": redirect_to,
        "magic_link": action_link,
        "message": "Fresh magic link ready. Copy and send to the user — single-use, expires in ~1 hour.",
    }


@router.get("/users", response_model=list[UserListResponse])
async def list_users(admin: AdminUser, db: DbSession):
    """List all users (admin only)."""
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        UserListResponse(id=str(u.id), email=u.email, name=u.name, role=u.role)
        for u in users
    ]


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    admin: AdminUser,
    db: DbSession,
    role: str = "user",
):
    """Update a user's role (admin only)."""
    if role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = role
    await db.commit()
    return {"status": "updated", "user_id": user_id, "role": role}


@router.post("/admin/run-discovery")
async def admin_run_discovery(admin: AdminUser):
    """Kick off every discovery source + a quick-score pass right now.
    Same code paths the Vercel cron uses — useful when a new user joins
    and you don't want to wait for 06:00 UTC for their inbox to populate.

    Runs everything concurrently so total wall time ~ slowest source
    (≈30–45 s in practice). Comfortably inside Vercel's 60 s budget.
    """
    import asyncio
    import time
    import logging
    log = logging.getLogger(__name__)

    from app.workers.discovery_tasks import (
        _run_curated_async, _run_arbeitnow_async,
        _run_remoteok_async, _run_himalayas_async,
        _run_remotive_async, _run_weworkremotely_async,
        _run_dailyremote_async, _run_undutchables_async,
        quick_score_all_users,
    )

    runners: list[tuple[str, callable]] = [
        ("curated", _run_curated_async),
        ("arbeitnow", _run_arbeitnow_async),
        ("remoteok", _run_remoteok_async),
        ("himalayas", _run_himalayas_async),
        ("remotive", _run_remotive_async),
        ("weworkremotely", _run_weworkremotely_async),
        ("dailyremote", _run_dailyremote_async),
        ("undutchables", _run_undutchables_async),
    ]

    async def _run_one(name: str, runner):
        started = time.monotonic()
        try:
            await runner()
            return name, f"ok ({time.monotonic() - started:.1f}s)"
        except Exception as e:  # noqa: BLE001
            log.error("admin run-discovery: %s failed: %s", name, e)
            return name, f"error: {type(e).__name__}: {e}"

    pairs = await asyncio.gather(*(_run_one(n, r) for n, r in runners))
    results = dict(pairs)
    scoring = await quick_score_all_users(per_user_timeout=10)
    return {"status": "complete", "results": results, "scoring": scoring}


@router.get("/admin/stale-jobs/preview")
async def admin_stale_jobs_preview(
    admin: AdminUser,
    db: DbSession,
    days: int = 30,
):
    """How many old jobs would the cleanup mark as expired? Caller can
    sanity-check the count before running the destructive endpoint.

    Stale = discovered more than `days` ago AND status is still in the
    pre-applied bucket (raw / normalized / enriched / scored / discovered
    / shortlisted). Jobs that someone applied to / interviewed for /
    archived manually are NEVER touched.
    """
    from sqlalchemy import select, func, text
    from app.models.job import Job

    # Use SQL interval literal — far less fragile than Python timedeltas.
    pre_applied = ("raw", "normalized", "deduplicated", "enriched",
                   "scored", "discovered", "shortlisted")
    count_q = (
        select(func.count(Job.id))
        .where(
            Job.status.in_(pre_applied),
            Job.discovered_at < func.now() - text(f"interval '{int(days)} days'"),
        )
    )
    count = (await db.execute(count_q)).scalar() or 0
    total_q = select(func.count(Job.id)).where(Job.status.in_(pre_applied))
    total = (await db.execute(total_q)).scalar() or 0
    return {"would_expire": count, "total_unapplied": total, "days": days}


@router.post("/admin/stale-jobs/cleanup")
async def admin_stale_jobs_cleanup(
    admin: AdminUser,
    db: DbSession,
    days: int = 30,
):
    """Mark stale unapplied jobs as 'expired' so they drop out of every
    user's inbox. Doesn't delete the rows — preserves them for audit
    and so application_tracking FKs don't break. Re-runnable: only
    flips rows currently in the pre-applied bucket."""
    from sqlalchemy import update, func as sa_func, text
    from app.models.job import Job

    pre_applied = ("raw", "normalized", "deduplicated", "enriched",
                   "scored", "discovered", "shortlisted")
    stmt = (
        update(Job)
        .where(
            Job.status.in_(pre_applied),
            Job.discovered_at < sa_func.now() - text(f"interval '{int(days)} days'"),
        )
        .values(status="expired")
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"expired": result.rowcount, "days": days}


@router.post("/admin/stale-jobs/cleanup-by-source")
async def admin_stale_jobs_cleanup_by_source(
    admin: AdminUser,
    db: DbSession,
    source: str,
    days: int = 14,
):
    """Source-specific age cleanup. Adzuna's free API only serves recent
    listings and their postings rotate within ~2–3 weeks, so anything
    we ingested via Adzuna more than 14 days ago is almost certainly
    gone from the underlying employer. Same pattern works for any
    aggregator that anti-bots us (we can't verify their URLs).

    Same safety guarantees as the generic cleanup: never touches jobs
    in the applied / interviewing / offered / archived buckets.
    """
    from sqlalchemy import update, select, func as sa_func, text
    from app.models.job import Job, JobSource

    pre_applied = ("raw", "normalized", "deduplicated", "enriched",
                   "scored", "discovered", "shortlisted")

    src_row = (await db.execute(
        select(JobSource.id).where(JobSource.name == source)
    )).first()
    if not src_row:
        raise HTTPException(status_code=404, detail=f"Source '{source}' not found")
    source_id = src_row[0]

    stmt = (
        update(Job)
        .where(
            Job.source_id == source_id,
            Job.status.in_(pre_applied),
            Job.discovered_at < sa_func.now() - text(f"interval '{int(days)} days'"),
        )
        .values(status="expired")
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"expired": result.rowcount, "source": source, "days": days}


@router.post("/admin/embeddings/test")
async def admin_embeddings_test(admin: AdminUser):
    """Embeds a single short string and returns the result so an
    operator can confirm VOYAGE_API_KEY is set + the network reaches
    api.voyageai.com. Surfaces the real error instead of the silent
    'backfill returned 0' state."""
    from app.services.scoring.embedder import embed_one
    try:
        vec = await embed_one("test connectivity to voyage", input_type="document")
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if vec is None:
        return {"ok": False, "error": "VOYAGE_API_KEY not configured (env var missing or empty)"}
    return {"ok": True, "dim": len(vec), "sample": vec[:5]}


@router.post("/admin/embeddings/backfill")
async def admin_embeddings_backfill(
    admin: AdminUser,
    db: DbSession,
    limit: int = 20,
):
    """Embed jobs that don't have a semantic vector yet.

    Internally loops up to a 45s wall-clock budget so a single button-
    click can clear hundreds of rows without the frontend having to
    chain. Each iteration embeds `limit` jobs in one batched Voyage
    call + one batched UPDATE, so the per-iteration cost is mostly
    Voyage latency (~3-5s) rather than DB round-trips.

    Previous design did one batch per HTTP call and asked the frontend
    to chain — that paid Vercel cold-start (~3-5s) + connection setup
    (~500ms) on every call. By batch 3 the third invocation hit a
    transient slow Voyage response and busted the 60s ceiling.
    """
    import asyncio
    import time
    from app.workers.discovery_tasks import _embed_unembedded_jobs

    bounded = min(max(int(limit), 1), 50)
    started = time.monotonic()
    BUDGET_S = 40.0  # leave 20s buffer under Vercel's 60s ceiling
    PER_ITER_TIMEOUT_S = 25.0  # cap any one iteration

    total_embedded = 0
    last_error: str | None = None
    iters = 0
    while time.monotonic() - started < BUDGET_S:
        iters += 1
        try:
            # asyncio.wait_for so a single hung Voyage call can't burn
            # the whole budget — partial progress so far is already
            # committed by _embed_unembedded_jobs per call.
            embedded = await asyncio.wait_for(
                _embed_unembedded_jobs(limit=bounded),
                timeout=PER_ITER_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            logger.warning("Backfill iter %d timed out after %ds", iters, PER_ITER_TIMEOUT_S)
            last_error = f"iteration {iters} exceeded {PER_ITER_TIMEOUT_S}s"
            break
        except Exception as e:  # noqa: BLE001
            logger.exception("Embeddings backfill iter %d failed", iters)
            last_error = f"{type(e).__name__}: {e}"
            break
        if embedded == 0:
            break  # nothing left to embed
        total_embedded += embedded
        # Stop early if we did less than the requested limit (queue drained).
        if embedded < bounded:
            break
        await asyncio.sleep(0.3)

    # Count remaining unembedded rows so the caller knows whether to
    # click again.
    from sqlalchemy import select, func
    from app.models.job import JobEntity
    remaining_q = (
        select(func.count(JobEntity.id)).where(JobEntity.embedding.is_(None))
    )
    remaining = (await db.execute(remaining_q)).scalar() or 0
    elapsed = time.monotonic() - started

    if last_error and total_embedded == 0:
        raise HTTPException(
            status_code=502,
            detail=f"Backfill failed: {last_error}",
        )
    return {
        "embedded": total_embedded,
        "remaining": remaining,
        "has_more": remaining > 0,
        "elapsed_s": round(elapsed, 1),
        "iterations": iters,
        "last_error": last_error,
    }


@router.get("/admin/debug/source-health")
async def admin_source_health(admin: AdminUser):
    """Ping every external job source and report whether it's actually
    producing jobs right now. Use this BEFORE wiring a source into a
    cron — and any time someone reports the inbox feels empty.

    Each source runs in isolation with its own try/except + 20s timeout
    so a hanging one can't kill the others. Returns count_fetched per
    source so you can spot 'API healthy but returning zero rows' vs
    'API broken' vs 'env var missing'.
    """
    import asyncio
    import time
    from app.core.config import get_settings
    cfg = get_settings()

    # Tuples of (display_name, callable that returns a list of raw job dicts,
    # required env var to flag if missing).
    probes: list[tuple[str, callable, str | None]] = []

    async def _probe_adzuna():
        from app.services.discovery.adzuna_service import fetch_jobs
        return await fetch_jobs(country_code="gb", keywords=["ai engineer"])
    probes.append(("adzuna", _probe_adzuna, "adzuna_app_key"))

    async def _probe_jsearch():
        from app.services.discovery.jsearch_service import fetch_jobs
        return await fetch_jobs(queries=["ai engineer"])
    probes.append(("jsearch", _probe_jsearch, "jsearch_rapidapi_key"))

    async def _probe_remoteok():
        from app.services.discovery.remoteok_service import fetch_jobs
        return await fetch_jobs(keywords={"ai", "engineer"})
    probes.append(("remoteok", _probe_remoteok, None))

    async def _probe_arbeitnow():
        from app.services.discovery.arbeitnow_service import fetch_jobs
        return await fetch_jobs(keywords={"ai", "engineer"})
    probes.append(("arbeitnow", _probe_arbeitnow, None))

    async def _probe_himalayas():
        from app.services.discovery.himalayas_service import fetch_jobs
        return await fetch_jobs(keywords={"ai", "engineer"})
    probes.append(("himalayas", _probe_himalayas, None))

    async def _probe_remotive():
        from app.services.discovery.remotive_service import fetch_jobs
        return await fetch_jobs(keywords={"ai", "engineer"})
    probes.append(("remotive", _probe_remotive, None))

    async def _probe_wwr():
        from app.services.discovery.weworkremotely_service import fetch_jobs
        return await fetch_jobs(keywords={"ai", "engineer"})
    probes.append(("weworkremotely", _probe_wwr, None))

    async def _probe_dailyremote():
        from app.services.discovery.dailyremote_service import fetch_jobs
        return await fetch_jobs(keywords={"ai", "engineer"})
    probes.append(("dailyremote", _probe_dailyremote, "firecrawl_api_key"))

    # Crossover removed from probe + cron: verified 2026-05 that
    # crossover.com/jobs is now a JS-rendered SPA — raw HTML has zero
    # job links. Firecrawl might render it correctly but unverified.
    # Lives in /discover-slow as a manual escape hatch.

    async def _probe_undutchables():
        from app.services.discovery.undutchables_service import fetch_jobs
        return await fetch_jobs(keywords=None, max_detail_fetches=2)
    probes.append(("undutchables", _probe_undutchables, "firecrawl_api_key"))

    async def _probe_workingnomads():
        from app.services.discovery.workingnomads_service import fetch_jobs
        return await fetch_jobs(keywords={"ai", "engineer"})
    probes.append(("workingnomads", _probe_workingnomads, None))

    # Arc.dev disabled from probe (and removed from cron in this push).
    # Verified 2026-05: /remote-jobs/<category> pages render only links
    # to other categories — individual job postings are JS-loaded via
    # a client-side query, so Firecrawl's static-render snapshot has
    # zero job-detail URLs to extract. Burns Firecrawl credits for no
    # return. Drop in /discover-slow as a manual escape hatch if Arc
    # ever brings back static job listings.

    async def _probe_wellfound():
        from app.services.discovery.wellfound_service import fetch_jobs
        return await fetch_jobs(
            user_roles=["AI Engineer"], max_detail_fetches=2,
        )
    probes.append(("wellfound", _probe_wellfound, "firecrawl_api_key"))

    async def _probe_jobberman():
        from app.services.discovery.jobberman_service import fetch_jobs
        return await fetch_jobs(max_detail_fetches=2)
    probes.append(("jobberman", _probe_jobberman, None))

    async def _probe_myjobmag():
        from app.services.discovery.myjobmag_service import fetch_jobs
        return await fetch_jobs(max_detail_fetches=2)
    probes.append(("myjobmag", _probe_myjobmag, "firecrawl_api_key"))

    async def _probe_curated():
        from app.services.discovery.curated_service import fetch_jobs
        return await fetch_jobs(keywords=None)
    probes.append(("curated", _probe_curated, None))

    async def run_one(name: str, fn, env_key: str | None) -> dict:
        # Flag missing env vars before even hitting the network — saves
        # 20s waiting for a sure failure.
        if env_key and not getattr(cfg, env_key, None):
            return {"source": name, "status": "skipped", "reason": f"env var {env_key} not set", "count": 0, "elapsed_s": 0.0}
        started = time.monotonic()
        # 35s — was 20s, but Firecrawl-backed scrapers (wellfound, arcdev,
        # myjobmag, undutchables, dailyremote) can legitimately take 25+s
        # to render their listing pages. 20s caused false-positive
        # "timeout" rows; 35s leaves enough headroom while still capping
        # the overall probe.
        SOURCE_PROBE_TIMEOUT = 35.0
        try:
            jobs = await asyncio.wait_for(fn(), timeout=SOURCE_PROBE_TIMEOUT)
            elapsed = time.monotonic() - started
            return {
                "source": name,
                "status": "ok" if jobs else "empty",
                "count": len(jobs) if jobs else 0,
                "elapsed_s": round(elapsed, 1),
                "sample_title": (jobs[0].get("title") if jobs else None),
            }
        except asyncio.TimeoutError:
            return {"source": name, "status": "timeout", "count": 0, "elapsed_s": SOURCE_PROBE_TIMEOUT}
        except Exception as e:  # noqa: BLE001
            return {
                "source": name,
                "status": "error",
                "count": 0,
                "elapsed_s": round(time.monotonic() - started, 1),
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            }

    results = await asyncio.gather(*(run_one(n, f, k) for n, f, k in probes))
    return {"sources": results}


@router.post("/admin/backfill-title-translations")
async def admin_backfill_title_translations(
    admin: AdminUser,
    db: DbSession,
    limit: int = 30,
):
    """Admin-button equivalent of the cron backfill: walks jobs whose
    title_en is NULL and language != "en", translates with Haiku, writes
    back. Hard-caps at `limit` per call so a single click never blows
    the Vercel 60s timeout. Re-runnable — translated rows have title_en
    non-NULL so they're skipped on the next pass.

    Cost: ~$0.00001/title × limit. Default 30 jobs ≈ $0.0003.
    """
    from sqlalchemy import select
    from app.models.job import Job
    from app.services.parsing.translator import translate_title_to_english

    translated = 0
    skipped_already_english = 0
    failed = 0
    inspected = 0

    rows = (await db.execute(
        select(Job).where(
            Job.title_en.is_(None),
            (Job.language.is_(None)) | (Job.language != "en"),
        ).limit(limit)
    )).scalars().all()

    for job in rows:
        inspected += 1
        title_en, lang = await translate_title_to_english(job.title)
        if lang is None:
            failed += 1
            continue
        if lang == "en" and not title_en:
            job.language = "en"
            skipped_already_english += 1
            continue
        job.title_en = title_en
        job.language = lang
        translated += 1

    await db.commit()

    return {
        "inspected": inspected,
        "translated": translated,
        "skipped_already_english": skipped_already_english,
        "failed": failed,
        "more_to_do": inspected >= limit,
    }


@router.post("/admin/backfill-description-translations")
async def admin_backfill_description_translations(
    admin: AdminUser,
    db: DbSession,
    limit: int = 10,
):
    """Translate full job descriptions for already-ingested non-English
    jobs. Heavier than the title backfill — descriptions are 50-200x
    longer, so each Haiku call takes 4-8s.

    Translations fire in PARALLEL via asyncio.gather (concurrency=5) so
    the batch's wall-clock time is roughly one Haiku roundtrip, not
    `limit` of them — earlier serial loop hit Vercel's 60s timeout
    around batch=10. With parallelism, limit=15 finishes in ~10s.

    Walks jobs whose language != "en" AND raw_description_en is NULL
    AND raw_description is not NULL. Re-runnable, idempotent.
    """
    import asyncio
    from sqlalchemy import select
    from app.models.job import Job
    from app.services.parsing.translator import translate_description_to_english

    translated = 0
    failed = 0
    cost_estimate_usd = 0.0

    rows = (await db.execute(
        select(Job).where(
            Job.language.is_not(None),
            Job.language != "en",
            Job.raw_description_en.is_(None),
            Job.raw_description.is_not(None),
        ).limit(limit)
    )).scalars().all()
    inspected = len(rows)

    # Concurrency cap — Haiku's per-key rate limit handles 5+ concurrent
    # comfortably, but more risks 429s on a hot account. 5 is the sweet
    # spot: ~5x speedup over serial, well under Anthropic's limits.
    sem = asyncio.Semaphore(5)

    async def translate_one(job):
        async with sem:
            return await translate_description_to_english(
                job.raw_description, job.language,
            )

    results = await asyncio.gather(*(translate_one(j) for j in rows))

    for job, result in zip(rows, results):
        if result is None:
            failed += 1
            continue
        job.raw_description_en = result
        translated += 1
        # Rough Haiku token cost: ~$0.80/M input + ~$4/M output. Job
        # descriptions average ~2KB ≈ 500 tokens each direction.
        # ~$0.0024 per translation. Multiply for the report.
        cost_estimate_usd += 0.0024

    await db.commit()

    return {
        "inspected": inspected,
        "translated": translated,
        "failed": failed,
        "more_to_do": inspected >= limit,
        "approx_cost_usd": round(cost_estimate_usd, 4),
    }


@router.post("/admin/fix/scrub-asset-apply-urls")
async def admin_scrub_asset_apply_urls(admin: AdminUser, db: DbSession):
    """Wipe Job.apply_url for any row where the cached value points at a
    static asset (font / css / image) instead of a job posting.

    Background: the resolver's body-scan accidentally returned font and
    asset URLs (e.g. metaboldlf-webfont-2017.woff) before the
    _looks_like_asset filter shipped. The next click on those jobs would
    re-trigger the popup-downloads-a-font bug. Resetting apply_url here
    forces the resolver to run again with the fix in place.

    Safe to re-run: only NULLs out rows that match the asset pattern.
    """
    from sqlalchemy import text
    # Use Postgres regex to find apply_url ending in obvious asset
    # extensions OR containing asset-directory hints.
    result = await db.execute(text(r"""
        UPDATE jobs
           SET apply_url = NULL
         WHERE apply_url IS NOT NULL
           AND (
                apply_url ~* '\.(woff2?|ttf|otf|eot|css|js|mjs|map|png|jpe?g|gif|svg|ico|webp|avif|pdf|zip|gz|xml|json|txt|mp4|webm|mp3|wav)(\?.*)?$'
                OR apply_url ~* '/(assets|static|fonts|_next|images|img|css|js|build|dist|public|media)/'
           )
        RETURNING id
    """))
    rows = result.fetchall()
    await db.commit()
    return {"scrubbed": len(rows)}


@router.post("/admin/fix/raw-description")
async def admin_fix_raw_description(
    admin: AdminUser,
    db: DbSession,
):
    """One-shot: copy raw_content → raw_description for any job where
    raw_description is empty. Fixes jobs that landed via the heuristic
    parser before the normalizer fallback was shipped — their
    raw_description was NULL, the Voyage embedder couldn't ingest them,
    they sat unscored and invisible in the inbox.

    Safe to re-run: only flips rows where raw_description IS NULL.
    """
    from sqlalchemy import text
    result = await db.execute(text("""
        UPDATE jobs
           SET raw_description = LEFT(raw_content, 4000)
         WHERE raw_description IS NULL
           AND raw_content IS NOT NULL
           AND length(raw_content) > 50
        RETURNING id
    """))
    rows = result.fetchall()
    await db.commit()
    return {"backfilled": len(rows)}


@router.get("/admin/debug/country-filter")
async def admin_debug_country_filter(
    admin: AdminUser,
    db: DbSession,
    limit: int = 20,
):
    """Diagnose why off-target-country jobs are landing in the inbox.

    Dumps:
      - admin's preferred_countries (does it match what you saved?)
      - the 20 most recent visible jobs in their inbox WITH the filter
        components: country, location, remote_type, and whether each
        location string mentions a blocked or preferred country/city.

    If preferred_countries is empty / null, the country filter doesn't
    run. If preferred_countries is set but a LatAm job still shows up,
    the row dump shows exactly which clause is letting it through.
    """
    from app.models.candidate import CandidateProfile
    from app.models.job import Job, JobSource
    from sqlalchemy import select
    from app.services.parsing.normalizer import COUNTRY_MAP, CITY_TO_COUNTRY

    # Admin's own preferences
    prof = (await db.execute(
        select(
            CandidateProfile.preferred_countries,
            CandidateProfile.remote_preference,
            CandidateProfile.target_roles,
        ).where(CandidateProfile.user_id == admin.id)
    )).first()
    pref_countries = list(prof[0] or []) if prof else []
    remote_pref = prof[1] if prof else None
    target_roles = list(prof[2] or []) if prof else []

    wanted = {c.upper() for c in pref_countries if c}

    # Sample the most-recent visible jobs (regardless of filter — we want
    # to see what's there before the filter, so we can spot which rows
    # are squeaking through it).
    sample_rows = (await db.execute(
        select(
            Job.id, Job.title, Job.company, Job.country,
            Job.location, Job.remote_type, JobSource.name,
        )
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .where(Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]))
        .order_by(Job.discovered_at.desc())
        .limit(min(max(int(limit), 1), 100))
    )).all()

    # Build the same blocked / preferred name lists the filter uses.
    blocked: set[str] = set()
    preferred: set[str] = set()
    for name, code in list(COUNTRY_MAP.items()) + list(CITY_TO_COUNTRY.items()):
        n = name.lower()
        if len(n) < 4:
            continue
        if code.upper() in wanted:
            preferred.add(n)
        else:
            blocked.add(n)

    import re as _re

    def _mentions(text: str | None, names: set[str]) -> list[str]:
        if not text:
            return []
        t = text.lower()
        hits: list[str] = []
        for n in names:
            if _re.search(r"\b" + _re.escape(n) + r"\b", t):
                hits.append(n)
        return hits

    rows = []
    for jid, title, company, country, location, remote_type, source in sample_rows:
        blocked_hits = _mentions(location, blocked)
        preferred_hits = _mentions(location, preferred)
        # Replay the filter logic:
        #   first pass keeps if: remote_type=full_remote OR country in wanted OR country IS NULL
        #   second pass drops if: location mentions blocked AND not preferred (and location is not NULL)
        first_pass_keep = (
            remote_type == "full_remote"
            or (country and country.upper() in wanted)
            or country is None
        )
        if location is None:
            second_pass_keep = True
        else:
            second_pass_keep = (not blocked_hits) or bool(preferred_hits)
        should_be_visible = first_pass_keep and second_pass_keep

        rows.append({
            "job_id": str(jid),
            "title": title,
            "company": company,
            "country": country,
            "location": location,
            "remote_type": remote_type,
            "source": source,
            "blocked_hits": blocked_hits,
            "preferred_hits": preferred_hits,
            "first_pass_keep": first_pass_keep,
            "second_pass_keep": second_pass_keep,
            "should_be_visible": should_be_visible,
        })

    # ── Now run the ACTUAL SQL filter and compare. If Python says a row
    # should be dropped but the SQL filter still returns it, the bug is
    # in the SQL translation (regex / clause).
    from app.services.jobs_filter import apply_user_filters
    sql_query = (
        select(Job.id)
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .where(Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]))
    )
    sql_query = apply_user_filters(
        sql_query,
        target_roles=target_roles,
        skills=None,
        blocked_sources=None,
        remote_preference=remote_pref,
        preferred_countries=pref_countries,
    )
    sql_keep_ids = {
        str(r[0]) for r in (await db.execute(sql_query)).all()
    }

    # Walk our diagnostic rows and tag SQL agreement.
    sql_disagreements: list[dict] = []
    for r in rows:
        sql_keeps_it = r["job_id"] in sql_keep_ids
        r["sql_keeps"] = sql_keeps_it
        # Bug surface: Python says drop, SQL says keep.
        if (not r["should_be_visible"]) and sql_keeps_it:
            sql_disagreements.append({
                "job_id": r["job_id"],
                "title": r["title"],
                "location": r["location"],
                "blocked_hits": r["blocked_hits"],
            })

    # Try to compile the actual filter SQL to a literal string for
    # inspection — surfaces what Postgres actually receives.
    try:
        from sqlalchemy.dialects import postgresql
        compiled_sql = str(
            sql_query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
    except Exception as e:  # noqa: BLE001
        compiled_sql = f"(compile failed: {e})"

    return {
        "preferred_countries": pref_countries,
        "preferred_countries_normalised": sorted(wanted),
        "remote_preference": remote_pref,
        "target_roles": target_roles,
        "blocked_names_count": len(blocked),
        "preferred_names_count": len(preferred),
        "sample_size": len(rows),
        "rows": rows,
        "sql_disagreements": sql_disagreements,
        "compiled_sql": compiled_sql,
    }


@router.post("/admin/stale-jobs/verify")
async def admin_stale_jobs_verify(
    admin: AdminUser,
    db: DbSession,
    limit: int = 100,
    age_days_min: int = 0,
):
    """Probe each unapplied job's apply_url and mark confirmed-dead ones
    as expired. Conservative — only flips on HTTP 404 / 410. See
    app.services.maintenance.url_verifier for the shared logic; the
    daily cron uses the same helper with a smaller batch."""
    from app.services.maintenance.url_verifier import verify_batch

    return await verify_batch(db, limit=limit, age_days_min=age_days_min)


@router.get("/admin/stale-jobs/verify-debug")
async def admin_stale_jobs_verify_debug(
    admin: AdminUser,
    db: DbSession,
    limit: int = 50,
):
    """Diagnostic: probe a small sample and return WHY each URL came back
    ambiguous, grouped by host. Used to figure out whether high-ambiguous
    counts are from anti-bot blocking (HTTP 403 / Cloudflare), timeouts,
    or genuine network errors — so we can adjust strategy host by host
    instead of guessing."""
    import asyncio
    import httpx
    from collections import defaultdict
    from sqlalchemy import select
    from app.models.job import Job
    from app.services.maintenance.url_verifier import (
        PRE_APPLIED_STATUSES, _PROBE_HEADERS,
    )

    bounded = min(max(int(limit), 1), 200)
    rows = (await db.execute(
        select(Job)
        .where(
            Job.status.in_(PRE_APPLIED_STATUSES),
            (Job.apply_url.is_not(None)) | (Job.job_url.is_not(None)),
        )
        .order_by(Job.discovered_at.asc().nulls_first())
        .limit(bounded)
    )).scalars().all()

    sem = asyncio.Semaphore(8)

    async def probe(client: httpx.AsyncClient, url: str) -> dict:
        try:
            host = httpx.URL(url).host or "(unknown)"
        except Exception:
            host = "(invalid-url)"
        try:
            async with sem:
                r = await client.head(url, headers=_PROBE_HEADERS, follow_redirects=True)
                if r.status_code in (405, 501):
                    r = await client.get(url, headers=_PROBE_HEADERS, follow_redirects=True)
                return {"host": host, "outcome": str(r.status_code)}
        except httpx.TimeoutException:
            return {"host": host, "outcome": "timeout"}
        except httpx.ConnectError as e:
            return {"host": host, "outcome": f"connect_error:{type(e).__name__}"}
        except Exception as e:  # noqa: BLE001
            return {"host": host, "outcome": f"{type(e).__name__}"}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=3.0, read=4.0, write=3.0, pool=3.0),
        follow_redirects=True,
    ) as client:
        results = await asyncio.gather(*(
            probe(client, j.apply_url or j.job_url or "") for j in rows
        ))

    # Group: { host: { outcome: count } }
    by_host: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_outcome: dict[str, int] = defaultdict(int)
    samples: list[dict] = []

    for j, r in zip(rows, results):
        host = r["host"]
        outcome = r["outcome"]
        by_host[host][outcome] += 1
        by_outcome[outcome] += 1
        if len(samples) < 30:
            samples.append({
                "url": (j.apply_url or j.job_url or "")[:200],
                "host": host,
                "outcome": outcome,
                "company": j.company,
                "title": j.title[:80] if j.title else None,
            })

    # Flatten to a sortable list, biggest hosts first.
    host_breakdown = sorted(
        [
            {"host": h, "total": sum(d.values()), "by_outcome": dict(d)}
            for h, d in by_host.items()
        ],
        key=lambda x: -x["total"],
    )

    return {
        "checked": len(rows),
        "by_outcome": dict(by_outcome),
        "by_host": host_breakdown,
        "samples": samples,
    }
