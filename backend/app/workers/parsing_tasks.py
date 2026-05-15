import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.workers.celery_app import celery_app
from app.core.database import create_worker_session
from app.models.candidate import Resume, CandidateProfile, CandidateWorkHistory, CandidateSkill, CandidateEducation, CandidateBullet
from app.services.parsing.resume_parser import parse_resume_content, build_bullets_from_parsed
from app.services.parsing.job_parser import parse_job_text
from app.services.storage import download_file

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.workers.parsing_tasks.parse_resume",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def parse_resume(self, resume_id: str, user_id: str):
    """Parse an uploaded resume into structured profile data."""
    try:
        _run_async(_parse_resume_async(resume_id, user_id))
    except Exception as exc:
        logger.error("Resume parsing failed for %s: %s", resume_id, exc)
        raise self.retry(exc=exc)


async def _parse_resume_async(resume_id: str, user_id: str):
    async with create_worker_session()() as db:
        # Get resume record
        result = await db.execute(select(Resume).where(Resume.id == resume_id))
        resume = result.scalar_one_or_none()
        if not resume:
            logger.error("Resume %s not found", resume_id)
            return

        # Idempotency guard: if this resume was already parsed, do nothing.
        # Without this, re-uploading or hitting the re-parse endpoint would
        # duplicate work_history / skills / education / bullets rows under
        # the profile.
        if resume.parsed_at is not None:
            logger.info("Resume %s already parsed at %s — skipping", resume_id, resume.parsed_at)
            return

        # Download file from storage
        # Extract bucket path from URL
        path = f"{user_id}/{resume.file_url.split('/')[-1]}"
        content = await download_file("resumes", path)

        # Parse with LLM
        parsed = await parse_resume_content(content, resume.source_type)

        # Store structured JSON on resume
        resume.structured_json = parsed
        resume.parsed_at = datetime.now(timezone.utc)

        # Get or create profile
        prof_result = await db.execute(
            select(CandidateProfile).where(CandidateProfile.user_id == user_id)
        )
        profile = prof_result.scalar_one_or_none()

        suggested_roles = parsed.get("target_roles") or []
        # Strip blanks and dedupe while preserving order.
        suggested_roles = list({r.strip(): None for r in suggested_roles if r and r.strip()}.keys())

        if not profile:
            profile = CandidateProfile(
                user_id=user_id,
                headline=parsed.get("headline"),
                master_summary=parsed.get("summary"),
                # Seed target_roles from the resume so a user who never
                # touches the profile form still gets a filtered inbox.
                target_roles=suggested_roles or None,
            )
            db.add(profile)
            await db.flush()
        else:
            # Update headline/summary from parsed data
            if parsed.get("headline"):
                profile.headline = parsed["headline"]
            if parsed.get("summary"):
                profile.master_summary = parsed["summary"]
            # Only auto-fill target_roles when the user hasn't picked any —
            # never overwrite an explicit user choice.
            if suggested_roles and not profile.target_roles:
                profile.target_roles = suggested_roles

            # When a profile already exists, the user is uploading an
            # UPDATED version of their resume (more experience, new
            # skills, etc.). Wipe the previously-parsed children and
            # rebuild from the new parse so the profile reflects the
            # latest resume only — otherwise we accumulate doubled
            # work history, doubled skills, and stale bullets.
            #
            # User-set fields on the profile row itself (target_roles,
            # preferred_countries, visa_statuses, remote_preference,
            # salary, search_keywords, blocked_sources) survive untouched.
            from sqlalchemy import delete
            await db.execute(
                delete(CandidateWorkHistory).where(CandidateWorkHistory.profile_id == profile.id)
            )
            await db.execute(
                delete(CandidateSkill).where(CandidateSkill.profile_id == profile.id)
            )
            await db.execute(
                delete(CandidateEducation).where(CandidateEducation.profile_id == profile.id)
            )
            await db.execute(
                delete(CandidateBullet).where(CandidateBullet.profile_id == profile.id)
            )
            await db.flush()

        # Populate work history from parsed data
        for i, entry in enumerate(parsed.get("work_history", [])):
            work = CandidateWorkHistory(
                profile_id=profile.id,
                company=entry["company"],
                title=entry["title"],
                start_date=_parse_date(entry.get("start_date")),
                end_date=_parse_date(entry.get("end_date")),
                description=entry.get("description"),
                bullets=entry.get("bullets", []),
                skills=entry.get("skills", []),
                domain_tags=entry.get("domain_tags", []),
                sort_order=i,
            )
            db.add(work)

        # Populate skills
        for skill_data in parsed.get("skills", []):
            skill = CandidateSkill(
                profile_id=profile.id,
                skill_name=skill_data["skill_name"],
                category=skill_data.get("category", "technical"),
                proficiency=skill_data.get("proficiency"),
            )
            db.add(skill)

        # Populate education
        for edu_data in parsed.get("education", []):
            edu = CandidateEducation(
                profile_id=profile.id,
                institution=edu_data["institution"],
                degree=edu_data.get("degree"),
                field=edu_data.get("field"),
                graduation_date=_parse_date(edu_data.get("graduation_date")),
            )
            db.add(edu)

        # Populate bullet bank
        for bullet_data in build_bullets_from_parsed(parsed):
            bullet = CandidateBullet(
                profile_id=profile.id,
                text=bullet_data["text"],
                domain_tags=bullet_data.get("domain_tags", []),
                role_tags=bullet_data.get("role_tags", []),
                keywords=bullet_data.get("keywords", []),
            )
            db.add(bullet)

        # Update profile links if found
        links = parsed.get("links")
        if links and not profile.links:
            profile.links = links

        await db.commit()
        logger.info("Successfully parsed resume %s for user %s", resume_id, user_id)

        # Embed the freshly-parsed profile for semantic scoring. Failures
        # are non-fatal — the scorer falls back to the rule-based path if
        # the embedding is missing. Done after commit so an embed error
        # can't roll back the parse work.
        try:
            from app.services.scoring.embedder import embed_one, profile_corpus
            wh_for_embed = [
                {
                    "title": w.title,
                    "company": w.company,
                    "bullets": w.bullets or [],
                }
                for w in profile.work_history
            ]
            skills_for_embed = [s.skill_name for s in profile.skills if s.skill_name]
            text = profile_corpus(
                target_roles=profile.target_roles or [],
                headline=profile.headline,
                summary=profile.master_summary,
                skills=skills_for_embed,
                work_history=wh_for_embed,
            )
            vector = await embed_one(text, input_type="query")
            if vector is not None:
                profile.embedding = vector
                await db.commit()
        except Exception as e:  # noqa: BLE001
            logger.warning("Profile embedding failed for user %s: %s", user_id, e)

        # Note: rescore is handled by the caller (candidates.upload_resume)
        # which awaits _batch_score_async directly. The scorer reads the
        # embedding written above to drive the semantic component.


@celery_app.task(name="app.workers.parsing_tasks.parse_job_from_url")
def parse_job_from_url(url: str):
    """Fetch a job page via Firecrawl and parse with Claude."""
    _run_async(_parse_job_from_url_async(url))


async def _parse_job_from_url_async(url: str):
    from app.services.discovery.firecrawl_service import scrape_url
    from app.services.parsing.normalizer import normalize_and_store_job
    from app.services.parsing.heuristic_parser import parse_job_heuristic

    # Scrape the page (Firecrawl, no Anthropic)
    page_content = await scrape_url(url)

    # Parse — try LLM first (rich entity extraction), fall back to a
    # heuristic parser when Anthropic returns a credit / rate-limit /
    # auth error. The fallback lets URL imports keep working when the
    # admin's API balance hits zero; the job lands in the inbox with
    # title + company + location populated and skills/keywords empty.
    # When the LLM path comes back online, future imports automatically
    # get the richer entity extraction.
    try:
        parsed = await parse_job_text(page_content)
    except Exception as e:  # noqa: BLE001
        msg = str(e).lower()
        if any(token in msg for token in (
            "credit balance is too low",
            "credit_balance",
            "insufficient_quota",
            "rate_limit",
            "rate limit",
            "401",
            "403",
            "invalid_api_key",
            "billing",
        )):
            logger.warning(
                "LLM parse failed for %s (%s) — falling back to heuristic parser",
                url, e,
            )
            parsed = parse_job_heuristic(url=url, markdown=page_content)
        else:
            raise

    # Normalize and store
    async with create_worker_session()() as db:
        await normalize_and_store_job(
            db=db,
            parsed_data=parsed,
            raw_content=page_content,
            source_name="manual",
            job_url=url,
        )
        await db.commit()


@celery_app.task(name="app.workers.parsing_tasks.parse_job_from_text")
def parse_job_from_text(text: str, source: str = "manual"):
    """Parse raw job text with Claude."""
    _run_async(_parse_job_from_text_async(text, source))


async def _parse_job_from_text_async(text: str, source: str) -> str | None:
    """Parse pasted job text into a Job row. Returns the new job's id
    so callers (e.g. the /import/text endpoint) can run follow-up work
    against it — typically the apply-link resolver, since user-pasted
    text often omits the source URL."""
    from app.services.parsing.normalizer import normalize_and_store_job

    parsed = await parse_job_text(text)

    async with create_worker_session()() as db:
        job = await normalize_and_store_job(
            db=db,
            parsed_data=parsed,
            raw_content=text,
            source_name=source,
        )
        await db.commit()
        return str(job.id) if job else None


def _parse_date(date_str: str | None):
    """Parse a date string, returning None if invalid."""
    if not date_str:
        return None
    try:
        from datetime import date
        parts = date_str.split("-")
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        elif len(parts) == 1:
            return date(int(parts[0]), 1, 1)
    except (ValueError, IndexError):
        pass
    return None
