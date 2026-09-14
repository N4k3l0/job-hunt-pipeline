import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.core.database import create_worker_session
from app.models.job import Job, JobEntity, JobSource
from app.models.user import User
from app.services.parsing.normalizer import (
    compute_canonical_hash,
    extract_city,
    normalize_country,
    classify_remote,
    get_or_create_source,
    normalize_url,
)
from app.services.deduplication.dedup_service import check_duplicate

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _ingest_raw_jobs(jobs: list[dict]) -> tuple[int, int]:
    """Process a batch of raw job dicts through the pipeline.

    Pipeline: bulk pre-filter → per-job dedup → normalize → store.
    Scoring is NOT done here — the cron handler calls _quick_score after
    all sources finish so this function stays cheap and bounded.
    """
    if not jobs:
        return 0, 0

    # Bulk pre-filter: load every existing canonical_hash + job_url in
    # one query, then short-circuit duplicates in memory before the
    # expensive per-row check_duplicate (4-5 DB queries each). With the
    # curated source landing 1000+ candidates per run, this turns a
    # 30-50s loop into ~2s.
    async with create_worker_session()() as db:
        seen_rows = await db.execute(
            select(Job.id, Job.canonical_hash, Job.job_url).where(
                Job.status.notin_(["raw"])
            )
        )
        ids_by_hash: dict[str, list] = {}
        ids_by_url: dict[str, list] = {}
        for job_id, h, u in seen_rows.all():
            if h:
                ids_by_hash.setdefault(h, []).append(job_id)
            if u:
                ids_by_url.setdefault(u, []).append(job_id)

    pre_filtered: list[dict] = []
    pre_skipped = 0
    still_listed: set = set()
    batch_hashes: set[str] = set()
    batch_urls: set[str] = set()
    for raw in jobs:
        # Compute the same fingerprint we'd compute downstream.
        company = raw.get("company", "Unknown")
        title = raw.get("title", "")
        location = raw.get("location")
        country = normalize_country(raw.get("country"))
        city = extract_city(location)
        canonical_hash = compute_canonical_hash(company, title, city, country)
        normalized_url = normalize_url(raw.get("job_url"))
        matches = ids_by_hash.get(canonical_hash, []) + (
            ids_by_url.get(normalized_url, []) if normalized_url else []
        )
        if matches:
            still_listed.update(matches)
            pre_skipped += 1
            continue
        # The same job twice in this batch (two sources, or a source that
        # repeats itself): keep the first. Checking only against the
        # database let 113 exact copies in.
        if canonical_hash in batch_hashes or (normalized_url and normalized_url in batch_urls):
            pre_skipped += 1
            continue
        batch_hashes.add(canonical_hash)
        if normalized_url:
            batch_urls.add(normalized_url)
        # Stash the precomputed values so we don't recompute them.
        raw["_canonical_hash"] = canonical_hash
        raw["_normalized_url"] = normalized_url
        pre_filtered.append(raw)

    logger.info(
        "Bulk pre-filter: %d candidates → %d to ingest (%d known dups skipped)",
        len(jobs), len(pre_filtered), pre_skipped,
    )

    # A source listing a job we already have means it's still open there.
    if still_listed:
        from sqlalchemy import update
        now = datetime.now(timezone.utc)
        ids = list(still_listed)
        async with create_worker_session()() as db:
            for start in range(0, len(ids), 1000):
                await db.execute(
                    update(Job).where(Job.id.in_(ids[start:start + 1000])).values(last_seen_at=now)
                )
            await db.commit()

    async with create_worker_session()() as db:
        stored = 0
        skipped = 0

        # Cache source records per (name, type) so we don't fire a DB
        # round trip for every candidate. With curated landing 1000+
        # rows that all share source_name="curated", this turns 1000
        # calls into 1.
        source_cache: dict[tuple[str, str], JobSource] = {}

        async def _resolve_source(name: str, stype: str) -> JobSource:
            key = (name, stype)
            cached = source_cache.get(key)
            if cached is not None:
                return cached
            src = await get_or_create_source(db, name, stype)
            source_cache[key] = src
            return src

        for raw in pre_filtered:
            try:
                company = raw.get("company", "Unknown")
                title = raw.get("title", "")
                location = raw.get("location")
                country = normalize_country(raw.get("country"))
                city = extract_city(location)
                external_id = raw.get("external_id")

                # Resolve source via the per-batch cache.
                source = await _resolve_source(
                    raw.get("source_name", "unknown"),
                    raw.get("source_type", "api"),
                )

                # Reuse the values we already computed in pre-filter rather
                # than recomputing the canonical hash and URL.
                normalized_url = raw.get("_normalized_url")
                canonical_hash = raw.get("_canonical_hash")

                # Bulk pre-filter already cleared canonical_hash + URL
                # collisions in O(1). Skipping the per-row `check_duplicate`
                # call (which fires 4-5 extra DB queries for source/external
                # ID matches and description similarity) keeps the cron
                # under budget — at the cost of slightly looser dedup on
                # the (source_id, external_id) and Jaccard-similarity axes.
                # In practice ATS sources have stable external_ids so this
                # is safe; if cross-source near-duplicates start sneaking
                # in we can re-enable for the affected sources.

                remote_type = (
                    raw.get("remote_type")
                    or classify_remote(location)
                    or classify_remote(title)
                    or classify_remote(raw.get("raw_description"), is_description=True)
                )

                # Pre-generate the Job UUID in Python so we can attach the
                # JobEntity in the same flush — no per-row `await
                # db.flush()` to round-trip to the DB and read back the
                # auto-generated id. With 1000 candidates that single
                # change saves 30+ seconds of latency. The Job model
                # already accepts an explicit `id`.
                job_id = uuid.uuid4()
                job = Job(
                    id=job_id,
                    external_id=external_id,
                    source_id=source.id,
                    company=company,
                    title=title,
                    location=location,
                    country=country,
                    remote_type=remote_type,
                    job_url=normalized_url,
                    apply_url=raw.get("apply_url"),
                    salary_text=raw.get("salary_text"),
                    salary_min=raw.get("salary_min"),
                    salary_max=raw.get("salary_max"),
                    salary_currency=raw.get("salary_currency"),
                    raw_description=raw.get("raw_description"),
                    raw_content=str(raw),
                    employment_type=raw.get("employment_type"),
                    seniority=raw.get("seniority"),
                    canonical_hash=canonical_hash,
                    status="enriched",
                    parsed_at=datetime.now(timezone.utc),
                    last_seen_at=datetime.now(timezone.utc),
                )
                db.add(job)

                # If we have description content, create basic entities.
                # Capture the visa-sponsorship flag too — Arbeitnow is the
                # only source that explicitly exposes it today, but if other
                # sources start returning it we want it without another
                # plumbing change.
                desc = raw.get("raw_description", "")
                visa_flag = raw.get("visa_sponsorship")
                eligible = raw.get("eligible_countries")
                if desc or visa_flag is not None or eligible:
                    entities = JobEntity(
                        job_id=job_id,
                        skills=raw.get("tags", []),
                        requirements=[],
                        keywords=[],
                        sponsorship_available=visa_flag if isinstance(visa_flag, bool) else None,
                        eligible_countries=eligible or None,
                    )
                    db.add(entities)

                stored += 1

            except Exception as e:
                logger.error("Failed to ingest job '%s': %s", raw.get("title"), e)
                continue

        await db.commit()
        logger.info("Ingestion complete: %d stored, %d duplicates skipped", stored, skipped)

    # Batched embedding pass for the rows we just inserted. Done in a
    # SECOND session after commit so the embed API failures can't roll
    # back the ingest. ~14 batches × 1-2s each for a 1.7k-job catalogue.
    # No-ops if Voyage isn't configured — scorer falls back to rules.
    if stored > 0:
        try:
            await _embed_unembedded_jobs(limit=stored + 50)
        except Exception as e:  # noqa: BLE001
            logger.warning("Post-ingest embedding pass failed: %s", e)

    return stored, skipped


async def _embed_unembedded_jobs(limit: int = 50) -> int:
    """Find JobEntity rows with NULL embedding, embed them, write back.

    Uses raw SQL deliberately — earlier ORM-based version had unclear
    failures during backfill (function returned 'Failed to fetch'
    without a usable error). Raw SQL sidesteps any SQLAlchemy / pgvector
    type-mapping issue at the cost of being slightly less typesafe.

    Returns count embedded.
    """
    from app.services.scoring.embedder import embed_texts, job_corpus
    from sqlalchemy import text

    async with create_worker_session()() as db:
        # Fetch rows missing an embedding via raw SQL — pulls everything
        # job_corpus needs in one round-trip without depending on the
        # JobEntity.embedding column type being correctly mapped.
        q = text("""
            SELECT je.id AS entity_id,
                   j.title, j.company, j.raw_description,
                   je.skills, je.requirements, je.keywords
            FROM job_entities je
            JOIN jobs j ON j.id = je.job_id
            WHERE je.embedding IS NULL
            LIMIT :limit
        """)
        result = await db.execute(q, {"limit": limit})
        rows = result.fetchall()
        if not rows:
            return 0

        corpora = [
            job_corpus(
                title=row.title or "",
                company=row.company or "",
                description=row.raw_description,
                skills=row.skills or [],
                requirements=row.requirements or [],
                keywords=row.keywords or [],
            )
            for row in rows
        ]

        vectors = await embed_texts(corpora, input_type="document")
        if vectors is None:
            return 0  # Voyage unconfigured.

        # Sequential UPDATEs, committed per-row. The earlier batched
        # VALUES-derived-table version returned "Failed to fetch" on
        # every iteration — pgvector's cast inside a multi-row VALUES
        # apparently doesn't play nicely with asyncpg's prepared
        # statement layer. Per-row UPDATE is slower (~150ms each on the
        # pooler) but each row that succeeds is persisted, so a mid-
        # batch failure doesn't lose work.
        for row, vector in zip(rows, vectors):
            vec_str = "[" + ",".join(f"{v:.6f}" for v in vector) + "]"
            await db.execute(
                text("UPDATE job_entities SET embedding = :vec WHERE id = :id"),
                {"vec": vec_str, "id": str(row.entity_id)},
            )
        await db.commit()
        logger.info("Embedded %d jobs (sequential UPDATE)", len(rows))
        return len(rows)


async def quick_score_all_users(per_user_timeout: int = 12) -> dict[str, str]:
    """Run a single bounded scoring pass for every user, in parallel.

    Called by cron handlers AFTER their sources finish, so ingest stays
    cheap and scoring is its own budget. Each user's pass is capped by
    the batch scorer (limit 300 newest unscored), and the wait_for here
    caps wall time per user — together they keep a misbehaving user from
    starving the others.
    """
    import asyncio
    import time
    from app.workers.scoring_tasks import _batch_score_async
    from app.models.user import User

    async with create_worker_session()() as db:
        users_result = await db.execute(select(User.id))
        user_ids = [str(row[0]) for row in users_result.all()]

    async def score_one(uid: str) -> tuple[str, str]:
        started = time.monotonic()
        try:
            await asyncio.wait_for(
                _batch_score_async(uid, rescore_all=False),
                timeout=per_user_timeout,
            )
            return uid, f"ok ({time.monotonic() - started:.1f}s)"
        except asyncio.TimeoutError:
            return uid, f"timeout after {time.monotonic() - started:.0f}s"
        except Exception as e:  # noqa: BLE001
            return uid, f"error: {type(e).__name__}: {e}"

    results = await asyncio.gather(*(score_one(uid) for uid in user_ids))
    return dict(results)


# ── Apify ────────────────────────────────────────────────────────────────────


@celery_app.task(
    name="app.workers.discovery_tasks.process_apify_results",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_apify_results(self, actor_run_id: str, actor_type: str = "linkedin"):
    """Fetch results from an Apify actor run and process them."""
    try:
        _run_async(_process_apify_async(actor_run_id, actor_type))
    except Exception as exc:
        logger.error("Apify processing failed for run %s: %s", actor_run_id, exc)
        raise self.retry(exc=exc)


async def _process_apify_async(actor_run_id: str, actor_type: str):
    from app.services.discovery.apify_service import fetch_dataset_items, ACTOR_NORMALIZERS

    items = await fetch_dataset_items(actor_run_id)
    if not items:
        logger.warning("No items found for Apify run %s", actor_run_id)
        return

    normalizer = ACTOR_NORMALIZERS.get(actor_type)
    if not normalizer:
        logger.error("Unknown actor type: %s", actor_type)
        return

    normalized = [normalizer(item) for item in items]
    await _ingest_raw_jobs(normalized)


# ── Keyword Collection ────────────────────────────────────────────────────────


# Core keywords that are ALWAYS in the discovery pool regardless of who is
# signed up. Without these, an early-user-base skewed toward AI ends up
# with zero PM strings in the keyword pool — which silently drops PM
# postings at the curated / RemoteOK / Arbeitnow filters and leaves new
# Note: there is no longer a hardcoded CORE_DISCOVERY_KEYWORDS set.
# The discovery pool is 100% user-driven. If no users want a role, we
# don't waste API calls searching for it. The pool grows automatically
# as new users join with new target_roles / skills.


async def _collect_all_keywords() -> list[str]:
    """Union of every user's target_roles + custom search_keywords +
    technical/tool skills. Deduplicated case-insensitively, sorted by
    frequency (the keyword the most users want appears first).

    Used by sources that take a keyword filter and can handle a moderate
    number of terms (RemoteOK / Arbeitnow / Himalayas / Remotive / WWR /
    DailyRemote — these fetch a feed and filter locally, so extra terms
    just relax the filter).

    Returns an EMPTY list if no users / no profiles have any of those
    fields populated. Callers should treat empty as "skip this source
    entirely" rather than substituting a hardcoded fallback — searching
    for nothing-in-particular pollutes the inbox for everyone.
    """
    from collections import Counter
    from app.models.candidate import CandidateProfile, CandidateSkill

    counter: Counter[str] = Counter()
    async with create_worker_session()() as db:
        # Roles + custom keywords from every profile.
        prof_result = await db.execute(
            select(CandidateProfile.search_keywords, CandidateProfile.target_roles)
        )
        for search_kw, target_roles in prof_result:
            for kw in (search_kw or []):
                cleaned = (kw or "").strip().lower()
                if len(cleaned) >= 2:
                    counter[cleaned] += 1
            for role in (target_roles or []):
                cleaned = (role or "").strip().lower()
                if len(cleaned) >= 2:
                    counter[cleaned] += 1

        # Technical + tool skills across every profile.
        skill_result = await db.execute(
            select(CandidateSkill.skill_name).where(
                CandidateSkill.category.in_(("technical", "tool"))
            )
        )
        for (skill_name,) in skill_result:
            cleaned = (skill_name or "").strip().lower()
            # Single letters / pure punctuation slip in if a user types
            # "C" or "+"; both would explode aggregator queries with noise.
            if len(cleaned) >= 2:
                counter[cleaned] += 1

    keywords = [kw for kw, _ in counter.most_common()]
    logger.info(
        "Discovery pool: %d unique keywords from user profiles (top 10: %s)",
        len(keywords), keywords[:10],
    )
    return keywords


async def _collect_user_countries() -> list[str]:
    """Union of every user's preferred_countries (2-letter ISO codes),
    deduplicated. Returns empty list when no users / no preferences.

    Used by sources that fan out per-country (Adzuna primarily) so we
    only spend API budget on countries someone actually targets. If a
    user adds NL to their preferences, the next cron picks it up; if
    the last user wanting CA leaves, CA stops being queried.
    """
    from app.models.candidate import CandidateProfile

    countries: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(select(CandidateProfile.preferred_countries))
        for (pref,) in result:
            for raw in (pref or []):
                code = (raw or "").strip().upper()
                if len(code) == 2 and code.isalpha():
                    countries.add(code)

    out = sorted(countries)
    logger.info(
        "User-driven country pool: %d countries %s",
        len(out), out or "(none — no users have preferred_countries set)",
    )
    return out


async def _collect_user_roles(limit: int = 8) -> list[str]:
    """Just target_roles + custom search_keywords (NO skills). Use for
    sources with a tight query budget where role-precision matters more
    than coverage breadth — Adzuna fans out per-country so each query
    multiplies cost, JSearch's RapidAPI free tier is rate-limited, etc.

    Returns the top `limit` keywords ordered by how many users want
    each one — high-overlap roles first so the budget covers the most
    users with the fewest calls.

    Empty list when no users have roles set. Callers should skip rather
    than substitute a default.
    """
    from collections import Counter
    from app.models.candidate import CandidateProfile

    counter: Counter[str] = Counter()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(CandidateProfile.search_keywords, CandidateProfile.target_roles)
        )
        for search_kw, target_roles in result:
            for kw in (search_kw or []):
                cleaned = (kw or "").strip().lower()
                if len(cleaned) >= 2:
                    counter[cleaned] += 1
            for role in (target_roles or []):
                cleaned = (role or "").strip().lower()
                if len(cleaned) >= 2:
                    counter[cleaned] += 1

    top = [kw for kw, _ in counter.most_common(limit)]
    logger.info(
        "Top-%d user-driven role keywords: %s",
        limit, top or "(none — no users have target_roles set)",
    )
    return top


# ── Adzuna ───────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_adzuna_discovery")
def run_adzuna_discovery():
    """Run scheduled Adzuna API discovery across all target countries."""
    _run_async(_run_adzuna_async())


async def _run_adzuna_async():
    """Adzuna's free tier rate-limits aggressively (~25 req/min). With
    8 countries × N keywords × concurrent fan-out we'd hit that limit
    instantly and start eating timeouts.

    Constraints we enforce here:
      - Top 4 most-overlapping user role keywords (no hardcoded set).
        If 5 users want "Product Manager" and 1 wants "Marketing
        Manager", we query both — but Product Manager runs first
        because more users benefit. New roles enter automatically as
        users join with new target_roles.
      - Skips entirely when no users have roles set yet (don't waste
        the API budget on generic searches that won't match anyone).
      - Concurrent country fan-out throttled with a semaphore to 3 at
        a time → at most 12 in-flight Adzuna calls (4 keywords × 3
        countries). Stays inside their rate limit.
    """
    import asyncio
    from app.services.discovery.adzuna_service import fetch_jobs, ADZUNA_COUNTRIES

    # Everything driven by user data — no hardcoded countries OR keywords.
    # Keywords: top 15 most-overlapping user target_roles.
    # Countries: intersection of users' preferred_countries with Adzuna's
    # supported set. If no one targets AU, AU never gets queried.
    adzuna_keywords = await _collect_user_roles(limit=15)
    if not adzuna_keywords:
        logger.info(
            "Adzuna: skipping — no users have target_roles set yet, "
            "nothing to search for"
        )
        return

    wanted_countries = await _collect_user_countries()
    if not wanted_countries:
        logger.info(
            "Adzuna: skipping — no users have preferred_countries set yet, "
            "nothing to search for"
        )
        return

    # Adzuna only has endpoints for a subset of ISO codes (no NG, JP, etc).
    # Intersect — anything missing here gets caught by other sources.
    supported_iso = set(ADZUNA_COUNTRIES.keys())
    runnable = [
        (iso, ADZUNA_COUNTRIES[iso])
        for iso in wanted_countries
        if iso in supported_iso
    ]
    if not runnable:
        logger.info(
            "Adzuna: skipping — none of the user-wanted countries (%s) are "
            "in Adzuna's supported set (%s). Other sources cover them.",
            wanted_countries, sorted(supported_iso),
        )
        return

    logger.info(
        "Adzuna: querying %d countries × %d keywords = %d calls",
        len(runnable), len(adzuna_keywords), len(runnable) * len(adzuna_keywords),
    )

    # Semaphore(2) keeps us safely under the ~25/min rate limit even on
    # the largest user base configurations.
    sem = asyncio.Semaphore(2)

    async def run_country(iso: str, code: str) -> list[dict]:
        async with sem:
            try:
                return await fetch_jobs(country_code=code, keywords=adzuna_keywords)
            except Exception as e:
                logger.error("Adzuna discovery failed for %s: %s", iso, e)
                return []

    batches = await asyncio.gather(*[
        run_country(iso, code) for iso, code in runnable
    ])
    all_jobs = [j for batch in batches for j in batch]
    if all_jobs:
        await _ingest_raw_jobs(all_jobs)


# ── RemoteOK ─────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_remoteok_discovery")
def run_remoteok_discovery():
    """Run scheduled RemoteOK API discovery."""
    _run_async(_run_remoteok_async())


async def _run_remoteok_async():
    from app.services.discovery.remoteok_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("RemoteOK discovery failed: %s", e)


# ── Arbeitnow ────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_arbeitnow_discovery")
def run_arbeitnow_discovery():
    """Run scheduled Arbeitnow API discovery."""
    _run_async(_run_arbeitnow_async())


async def _run_arbeitnow_async():
    from app.services.discovery.arbeitnow_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(
            visa_sponsorship=False,
            keywords=set(keywords) if keywords else None,
        )
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Arbeitnow discovery failed: %s", e)


# ── JSearch ──────────────────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_jsearch_discovery")
def run_jsearch_discovery():
    """Run scheduled JSearch API discovery."""
    _run_async(_run_jsearch_async())


async def _run_jsearch_async():
    """JSearch is RapidAPI-rate-limited (free tier ~150 req/month).
    Use top 5 user roles only so the daily run stays inside budget
    (5 queries × 30 days = 150/month — at the wire). Skip if no users
    have roles set."""
    from app.services.discovery.jsearch_service import fetch_jobs

    queries = await _collect_user_roles(limit=5)
    if not queries:
        logger.info(
            "JSearch: skipping — no users have target_roles set yet"
        )
        return
    try:
        jobs = await fetch_jobs(queries=queries)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("JSearch discovery failed: %s", e)


# ── Himalayas (Nigeria-friendly remote board) ────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_himalayas_discovery")
def run_himalayas_discovery():
    """Run scheduled Himalayas API discovery — biased toward Nigeria-eligible roles."""
    _run_async(_run_himalayas_async())


async def _run_himalayas_async():
    from app.services.discovery.himalayas_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Himalayas discovery failed: %s", e)


# ── Remotive (Nigeria-friendly remote board) ─────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_remotive_discovery")
def run_remotive_discovery():
    """Run scheduled Remotive API discovery — filters to candidate-location-friendly roles."""
    _run_async(_run_remotive_async())


async def _run_remotive_async():
    from app.services.discovery.remotive_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Remotive discovery failed: %s", e)


# ── WeWorkRemotely (RSS) ─────────────────────────────────────────────────────


@celery_app.task(name="app.workers.discovery_tasks.run_weworkremotely_discovery")
def run_weworkremotely_discovery():
    """Run scheduled WeWorkRemotely RSS discovery."""
    _run_async(_run_weworkremotely_async())


async def _run_weworkremotely_async():
    from app.services.discovery.weworkremotely_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("WeWorkRemotely discovery failed: %s", e)


# ── Crossover (Firecrawl scrape; small, Nigeria-friendly catalog) ────────────


@celery_app.task(name="app.workers.discovery_tasks.run_crossover_discovery")
def run_crossover_discovery():
    """Run scheduled Crossover discovery via Firecrawl scraping."""
    _run_async(_run_crossover_async())


async def _run_crossover_async():
    from app.services.discovery.crossover_service import fetch_jobs
    from app.services.parsing.normalizer import normalize_url

    keywords = await _collect_all_keywords()

    # Pull URLs we already have for Crossover and skip them — saves Firecrawl
    # credits since the catalog moves slowly.
    skip_urls: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job.job_url).join(JobSource, Job.source_id == JobSource.id)
            .where(JobSource.name == "crossover", Job.job_url.is_not(None))
        )
        for row in result.all():
            normalized = normalize_url(row[0])
            if normalized:
                skip_urls.add(normalized)

    try:
        jobs = await fetch_jobs(
            keywords=set(keywords) if keywords else None,
            skip_urls=skip_urls,
        )
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Crossover discovery failed: %s", e)


# ── Undutchables (NL specialist recruiter; Firecrawl scrape) ─────────────────


async def _run_undutchables_async():
    """Scrape Undutchables — a Netherlands-focused recruiter that places
    international (non-Dutch-speaking) candidates. Costs ~13 Firecrawl
    credits per run (1 listing + 12 detail pages capped).
    """
    from app.services.discovery.undutchables_service import fetch_jobs
    from app.services.parsing.normalizer import normalize_url

    keywords = await _collect_all_keywords()

    # Skip URLs already in our DB so we don't re-spend credits on the
    # same posting every run. Same pattern as Crossover.
    skip_urls: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job.job_url).join(JobSource, Job.source_id == JobSource.id)
            .where(JobSource.name == "undutchables", Job.job_url.is_not(None))
        )
        for row in result.all():
            normalized = normalize_url(row[0])
            if normalized:
                skip_urls.add(normalized)

    try:
        jobs = await fetch_jobs(
            keywords=set(keywords) if keywords else None,
            skip_urls=skip_urls,
        )
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Undutchables discovery failed: %s", e)


# ── Curated companies (Greenhouse / Lever / Ashby direct) ───────────────────


async def _run_curated_async():
    """Highest-signal source: poll a hand-picked list of remote-friendly
    companies on free public ATSes. Apply URLs are clean by construction
    (boards.greenhouse.io / jobs.lever.co / jobs.ashbyhq.com), so
    swipe-to-apply works end-to-end without redirect resolution.

    We deliberately skip the keyword filter here. The 117 curated
    companies are already pre-filtered for quality, and dropping their
    listings because the title doesn't contain a current user's tech
    skills was silently starving PM users of supply — Asana/Calendly/etc.
    post tons of PM roles whose titles never say 'python' or 'ml'. The
    per-user inbox filter (apply_user_filters) is the right place to
    decide what each user sees; ingest should keep the catalog wide.
    """
    from app.services.discovery.curated_service import fetch_jobs

    try:
        jobs = await fetch_jobs(keywords=None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Curated discovery failed: %s", e)


# ── DailyRemote (Cloudflare-gated remote board, ld+json scraping) ────────────


@celery_app.task(name="app.workers.discovery_tasks.run_dailyremote_discovery")
def run_dailyremote_discovery():
    """Run scheduled DailyRemote discovery — scrapes JobPosting JSON-LD."""
    _run_async(_run_dailyremote_async())


async def _run_dailyremote_async():
    from app.services.discovery.dailyremote_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("DailyRemote discovery failed: %s", e)


# ── Working Nomads (public JSON feed, no auth) ────────────────────────────────


async def _run_workingnomads_async():
    """Working Nomads exposes a free JSON feed at /api/exposed_jobs/.
    ~40-80 active rows per poll, ~65% Development category — strong
    supply for AI Eng / ML / Automation users."""
    from app.services.discovery.workingnomads_service import fetch_jobs

    keywords = await _collect_all_keywords()
    try:
        jobs = await fetch_jobs(keywords=set(keywords) if keywords else None)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Working Nomads discovery failed: %s", e)


# ── Arc.dev (JS SPA via Firecrawl, AI-focused categories) ─────────────────────


async def _run_arcdev_async():
    """Arc.dev curates remote jobs with deep category targeting at
    /remote-jobs/<slug>. Categories visited are driven by the union of
    all users' target_roles (mapped to Arc-known slugs). Skips entirely
    when no user roles map to any Arc category — don't waste Firecrawl
    credits searching for roles no user wants.
    Costs ~30 Firecrawl credits/run when active.
    """
    from app.services.discovery.arcdev_service import fetch_jobs
    from app.services.parsing.normalizer import normalize_url

    user_roles = await _collect_user_roles(limit=20)
    if not user_roles:
        logger.info("Arc.dev: skipping — no users have target_roles set")
        return

    # Skip URLs already in our DB to save Firecrawl credits.
    skip_urls: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job.job_url).join(JobSource, Job.source_id == JobSource.id)
            .where(JobSource.name == "arcdev", Job.job_url.is_not(None))
        )
        for row in result.all():
            normalized = normalize_url(row[0])
            if normalized:
                skip_urls.add(normalized)
    try:
        jobs = await fetch_jobs(
            user_roles=user_roles,
            skip_urls=skip_urls,
        )
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Arc.dev discovery failed: %s", e)


# ── Wellfound (formerly AngelList — startups via Firecrawl) ──────────────────


async def _run_wellfound_async():
    """Wellfound serves startup roles, often with direct apply. Plain
    HTTP gets 403'd (anti-bot); Firecrawl handles. Roles visited driven
    by users' target_roles (mapped to Wellfound-known slugs). Skips
    entirely when no user role maps to a known slug.
    ~18 credits/run when active."""
    from app.services.discovery.wellfound_service import fetch_jobs
    from app.services.parsing.normalizer import normalize_url

    user_roles = await _collect_user_roles(limit=20)
    if not user_roles:
        logger.info("Wellfound: skipping — no users have target_roles set")
        return

    skip_urls: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job.job_url).join(JobSource, Job.source_id == JobSource.id)
            .where(JobSource.name == "wellfound", Job.job_url.is_not(None))
        )
        for row in result.all():
            normalized = normalize_url(row[0])
            if normalized:
                skip_urls.add(normalized)
    try:
        jobs = await fetch_jobs(user_roles=user_roles, skip_urls=skip_urls)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Wellfound discovery failed: %s", e)


# ── Jobberman (Nigeria's largest job board, plain HTML scrape) ──────────────


async def _run_jobberman_async():
    """Jobberman covers Nigeria-local jobs (mostly Lagos / Abuja). Plain
    httpx scrape — no Firecrawl, no API key. Only runs if at least one
    user has Nigeria (NG) in preferred_countries — wastes nothing if
    no user wants NG coverage."""
    from app.services.discovery.jobberman_service import fetch_jobs
    from app.services.parsing.normalizer import normalize_url

    countries = await _collect_user_countries()
    if "NG" not in countries:
        logger.info("Jobberman: skipping — no users have NG in preferred_countries")
        return

    skip_urls: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job.job_url).join(JobSource, Job.source_id == JobSource.id)
            .where(JobSource.name == "jobberman", Job.job_url.is_not(None))
        )
        for row in result.all():
            normalized = normalize_url(row[0])
            if normalized:
                skip_urls.add(normalized)
    try:
        jobs = await fetch_jobs(skip_urls=skip_urls)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("Jobberman discovery failed: %s", e)


# ── MyJobMag (Nigeria #2; JS-rendered, Firecrawl required) ──────────────────


async def _run_myjobmag_async():
    """MyJobMag is Nigeria's #2 board. Like Jobberman, only runs when a
    user wants NG. Firecrawl-based since the page is JS-rendered.
    ~10 credits/run."""
    from app.services.discovery.myjobmag_service import fetch_jobs
    from app.services.parsing.normalizer import normalize_url

    countries = await _collect_user_countries()
    if "NG" not in countries:
        logger.info("MyJobMag: skipping — no users have NG in preferred_countries")
        return

    skip_urls: set[str] = set()
    async with create_worker_session()() as db:
        result = await db.execute(
            select(Job.job_url).join(JobSource, Job.source_id == JobSource.id)
            .where(JobSource.name == "myjobmag", Job.job_url.is_not(None))
        )
        for row in result.all():
            normalized = normalize_url(row[0])
            if normalized:
                skip_urls.add(normalized)
    try:
        jobs = await fetch_jobs(skip_urls=skip_urls)
        if jobs:
            await _ingest_raw_jobs(jobs)
    except Exception as e:
        logger.error("MyJobMag discovery failed: %s", e)
