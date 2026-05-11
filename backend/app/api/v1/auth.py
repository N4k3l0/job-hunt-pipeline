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
        _run_dailyremote_async, quick_score_all_users,
    )

    runners: list[tuple[str, callable]] = [
        ("curated", _run_curated_async),
        ("arbeitnow", _run_arbeitnow_async),
        ("remoteok", _run_remoteok_async),
        ("himalayas", _run_himalayas_async),
        ("remotive", _run_remotive_async),
        ("weworkremotely", _run_weworkremotely_async),
        ("dailyremote", _run_dailyremote_async),
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
    limit: int = 200,
):
    """Embed jobs that don't have a semantic vector yet. Used to bring
    the historical catalog up to date after the embedding migration —
    new jobs ingested after that point get embedded inline during
    discovery, so this only matters for pre-existing rows.

    Batches of up to 128 jobs per Voyage call. The caller chains calls
    via has_more until the catalogue is fully embedded.
    """
    from app.workers.discovery_tasks import _embed_unembedded_jobs
    embedded = await _embed_unembedded_jobs(limit=min(max(int(limit), 1), 500))

    # Quick check: how many rows still need embedding after this pass?
    from sqlalchemy import select, func
    from app.models.job import JobEntity
    remaining_q = (
        select(func.count(JobEntity.id)).where(JobEntity.embedding.is_(None))
    )
    remaining = (await db.execute(remaining_q)).scalar() or 0
    return {
        "embedded": embedded,
        "remaining": remaining,
        "has_more": remaining > 0,
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
