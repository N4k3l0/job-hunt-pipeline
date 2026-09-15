import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobDuplicate

logger = logging.getLogger(__name__)


def jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts based on word tokens."""
    if not text_a or not text_b:
        return 0.0
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


async def check_duplicate(
    db: AsyncSession,
    canonical_hash: str,
    description: str = "",
    similarity_threshold: float = 0.7,
    title: str = "",
    company: str = "",
    source_id: str | None = None,
    external_id: str | None = None,
    job_url: str | None = None,
) -> tuple[bool, str | None]:
    """Check if a job is a duplicate using multi-layer deduplication.

    Layer 0a: same (source_id, external_id) — fastest, most reliable; also
              prevents IntegrityError on the unique index when a source
              re-emits the same job.
    Layer 0b: same normalized job_url — catches re-runs with shifted titles.
    Layer 1: Exact canonical hash match
    Layer 1.5: Same title + company (catches location variants)
    Layer 2: Description similarity for near-matches

    Returns:
        (is_duplicate, duplicate_of_job_id)
    """
    # Layer 0a: same (source, external_id) — guaranteed dup when present.
    if source_id and external_id:
        result = await db.execute(
            select(Job).where(
                Job.source_id == source_id,
                Job.external_id == external_id,
            ).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.debug("source+external_id match: %s", existing.id)
            return True, str(existing.id)

    # Layer 0b: same job URL (after stripping trailing slashes / tracking params).
    if job_url:
        from app.services.parsing.normalizer import normalize_url
        normalized = normalize_url(job_url)
        if normalized:
            result = await db.execute(
                select(Job).where(Job.job_url == normalized).limit(1)
            )
            existing = result.scalar_one_or_none()
            if existing:
                logger.debug("job_url match: %s", existing.id)
                return True, str(existing.id)

    # Layer 1: Exact hash match
    result = await db.execute(
        select(Job).where(Job.canonical_hash == canonical_hash).limit(1)
    )
    existing = result.scalar_one_or_none()

    if existing:
        logger.debug("Exact hash match found: %s", existing.id)
        return True, str(existing.id)

    # Layer 1.5: Same title + company (different locations of same job)
    if title and company:
        from app.services.parsing.normalizer import normalize_company, normalize_title
        result = await db.execute(
            select(Job).where(
                func.lower(Job.title) == normalize_title(title),
                func.lower(Job.company) == normalize_company(company),
            ).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing:
            logger.debug("Title+company match found: %s", existing.id)
            return True, str(existing.id)

    # Layer 2: If we have a description, check similar jobs
    if description and len(description) > 50:
        # Get recent jobs for similarity check (limit scope for performance)
        result = await db.execute(
            select(Job)
            .where(Job.status != "duplicate")
            .order_by(Job.discovered_at.desc())
            .limit(200)
        )
        recent_jobs = result.scalars().all()

        for job in recent_jobs:
            if not job.raw_description:
                continue

            similarity = jaccard_similarity(description, job.raw_description)
            if similarity >= similarity_threshold:
                logger.info(
                    "Similar job found (%.2f similarity): %s at %s",
                    similarity,
                    job.title,
                    job.company,
                )
                # Record the duplicate relationship
                dup = JobDuplicate(
                    job_id=job.id,  # Will be updated when the new job is created
                    duplicate_of_job_id=job.id,
                    confidence=similarity,
                    method="similarity",
                )
                db.add(dup)
                return True, str(job.id)

    return False, None

