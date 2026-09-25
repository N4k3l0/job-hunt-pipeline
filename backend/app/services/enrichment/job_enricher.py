"""Read incoming job postings with a small model and store the facts the
scorer and inbox filters need: skills, requirements, seniority, salary,
visa sponsorship and which countries a remote role accepts.

Most discovery sources only give us a title, a location and a free-text
description, so without this step skill and seniority scoring has almost
nothing to compare against a resume.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import defer, selectinload

from app.core.database import create_worker_session
from app.llm.client import LLMCreditsExhausted, credits_paused, llm_client
from app.llm.prompts.enrich_job import RECORD_TOOL, SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.models.job import Job, JobEntity
from app.models.scoring import JobScore
from app.services.parsing.html_text import strip_html

logger = logging.getLogger(__name__)

DESCRIPTION_CHAR_LIMIT = 6000
# Postings shorter than this carry too little to extract; they're marked
# enriched without a model call so they aren't picked up again.
MIN_DESCRIPTION_CHARS = 200
MAX_LIST_ITEMS = 25

_WHITESPACE_RE = re.compile(r"\s+")

_SENIORITIES = {"entry", "mid", "senior", "lead", "director", "vp", "c_level"}
_EMPLOYMENT_TYPES = {"full_time", "part_time", "contract", "freelance", "internship"}
_REMOTE_TYPES = {"full_remote", "hybrid", "onsite"}

# Multipliers to an annual amount. Weekly/daily assume a 52-week,
# 260-working-day year; hourly assumes 2,080 hours.
_ANNUAL_MULTIPLIER = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1}
# Below this, an amount with no stated period can't be an annual salary.
_MIN_PLAUSIBLE_ANNUAL = 1000


@dataclass
class EnrichmentResult:
    selected: int = 0
    enriched: int = 0
    skipped_short: int = 0
    failed: int = 0
    job_ids: list[UUID] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # The Anthropic credits ran out. Unread jobs stay unread for next time.
    paused: bool = False


def clean_description(raw: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", strip_html(raw)).strip()


def _clean_list(value, limit: int = MAX_LIST_ITEMS) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s[:200])
        if len(out) >= limit:
            break
    return out


def _clean_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value >= 0 else None


def _enum_value(value, allowed: set[str]) -> str | None:
    """The model sometimes wraps a single enum value in a list
    (["entry"]); take the first allowed value either way."""
    candidates = value if isinstance(value, list) else [value]
    for item in candidates:
        if isinstance(item, str) and item in allowed:
            return item
    return None


def annual_salary(amount, period) -> int | None:
    value = _clean_int(amount)
    if not value:
        return None
    period = _enum_value(period, set(_ANNUAL_MULTIPLIER))
    if period is None:
        return value if value >= _MIN_PLAUSIBLE_ANNUAL else None
    return value * _ANNUAL_MULTIPLIER[period]


def _clean_countries(value) -> list[str]:
    codes = {
        c.strip().upper()
        for c in (value if isinstance(value, list) else [])
        if isinstance(c, str) and len(c.strip()) == 2 and c.strip().isalpha()
    }
    codes.discard("WW")
    return sorted(codes)


def apply_extraction(job: Job, entity: JobEntity, extracted: dict, now: datetime) -> None:
    """Write extracted facts onto the job. Source-provided values on the
    job row win; the entity's lists are replaced when the model found any."""
    skills = _clean_list(extracted.get("required_skills"))
    if skills:
        entity.skills = skills
    entity.nice_to_have = _clean_list(extracted.get("nice_to_have_skills"))
    entity.requirements = _clean_list(extracted.get("requirements"), limit=15)
    entity.keywords = _clean_list(extracted.get("keywords"), limit=15)

    years_min = _clean_int(extracted.get("years_experience_min"))
    years_max = _clean_int(extracted.get("years_experience_max"))
    if years_min is not None:
        entity.years_experience_min = years_min
    if years_max is not None:
        entity.years_experience_max = years_max

    countries = _clean_countries(extracted.get("eligible_countries"))
    if countries:
        entity.eligible_countries = countries

    sponsorship = extracted.get("sponsorship_available")
    if isinstance(sponsorship, bool) and entity.sponsorship_available is None:
        entity.sponsorship_available = sponsorship
    visa_notes = extracted.get("visa_notes")
    if isinstance(visa_notes, str) and visa_notes.strip() and not entity.visa_notes:
        entity.visa_notes = visa_notes.strip()[:1000]

    seniority = _enum_value(extracted.get("seniority"), _SENIORITIES)
    if job.seniority is None and seniority:
        job.seniority = seniority
    employment_type = _enum_value(extracted.get("employment_type"), _EMPLOYMENT_TYPES)
    if job.employment_type is None and employment_type:
        job.employment_type = employment_type
    remote_type = _enum_value(extracted.get("remote_type"), _REMOTE_TYPES)
    if job.remote_type is None and remote_type:
        job.remote_type = remote_type

    period = extracted.get("salary_period")
    salary_min = annual_salary(extracted.get("salary_min"), period)
    salary_max = annual_salary(extracted.get("salary_max"), period)
    # Extracted salaries vary between runs on the same posting; drop
    # ranges that can't be right rather than store a misleading number.
    if salary_min and salary_max and (salary_min > salary_max or salary_max > 5 * salary_min):
        salary_min = salary_max = None
    currency = extracted.get("salary_currency")
    if job.salary_min is None and job.salary_max is None and (salary_min or salary_max):
        job.salary_min = salary_min
        job.salary_max = salary_max
        if isinstance(currency, str) and len(currency.strip()) == 3:
            job.salary_currency = currency.strip().upper()

    entity.enriched_at = now


async def extract_job_details(job: Job) -> dict:
    description = clean_description(job.raw_description_en or job.raw_description)
    prompt = USER_PROMPT_TEMPLATE.format(
        title=job.title_en or job.title or "",
        company=job.company or "",
        location=job.location or "Not stated",
        description=description[:DESCRIPTION_CHAR_LIMIT],
    )
    return await llm_client.generate_structured(
        task_type="extraction",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        tools=[RECORD_TOOL],
        max_tokens=1500,
    )


async def enrich_pending_jobs(
    *,
    limit: int = 25,
    max_age_days: int = 30,
    concurrency: int = 8,
    time_budget_seconds: float = 40.0,
    per_call_timeout_seconds: float = 30.0,
) -> EnrichmentResult:
    """Enrich up to `limit` recent visible jobs that haven't been read yet:
    the best match for any user first, then newest first. Reading tells
    the scorer a job's level and skills, and an unread job's score stays low
    while they're unknown, so the most promising jobs go first rather than
    only those already in an inbox. Stops starting new model calls once the
    time budget is spent."""
    started = time.monotonic()
    result = EnrichmentResult()
    if credits_paused():
        result.paused = True
        return result
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    # Looked up per job through ix_job_scores_job_fit; aggregating every
    # score first took ~3s on the production database.
    best_score = (
        select(func.max(JobScore.overall_fit))
        .where(JobScore.job_id == Job.id)
        .correlate(Job)
        .scalar_subquery()
    )

    async with create_worker_session()() as db:
        rows = (await db.execute(
            select(Job)
            .outerjoin(JobEntity, JobEntity.job_id == Job.id)
            .where(
                Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]),
                Job.discovered_at >= cutoff,
                or_(JobEntity.id.is_(None), JobEntity.enriched_at.is_(None)),
            )
            .order_by(best_score.desc().nulls_last(), Job.discovered_at.desc())
            .limit(limit)
            .options(defer(Job.raw_content), selectinload(Job.entities))
        )).scalars().all()
        result.selected = len(rows)
        now = datetime.now(timezone.utc)

        to_extract: list[tuple[Job, JobEntity]] = []
        for job in rows:
            entity = job.entities
            if entity is None:
                entity = JobEntity(job_id=job.id, skills=[], requirements=[], keywords=[])
                db.add(entity)
                job.entities = entity
            if len(clean_description(job.raw_description_en or job.raw_description)) < MIN_DESCRIPTION_CHARS:
                entity.enriched_at = now
                result.skipped_short += 1
                continue
            to_extract.append((job, entity))

        semaphore = asyncio.Semaphore(concurrency)

        async def run_one(job: Job) -> dict | Exception | None:
            async with semaphore:
                if time.monotonic() - started > time_budget_seconds:
                    return None  # out of budget; picked up next run
                try:
                    return await asyncio.wait_for(
                        extract_job_details(job), timeout=per_call_timeout_seconds
                    )
                except Exception as e:  # noqa: BLE001
                    return e

        outcomes = await asyncio.gather(*(run_one(job) for job, _ in to_extract))

        for (job, entity), outcome in zip(to_extract, outcomes):
            if outcome is None:
                continue
            if isinstance(outcome, LLMCreditsExhausted):
                result.paused = True  # not the job's fault; read it once credits are back
                continue
            if isinstance(outcome, Exception) or "text" in outcome:
                result.failed += 1
                message = f"{type(outcome).__name__}: {outcome}" if isinstance(outcome, Exception) else "no tool call"
                result.errors.append(f"{job.id}: {message}"[:300])
                continue
            try:
                apply_extraction(job, entity, outcome, now)
            except Exception as e:  # noqa: BLE001 — one odd record mustn't lose the batch
                result.failed += 1
                result.errors.append(f"{job.id}: apply failed: {type(e).__name__}: {e}"[:300])
                continue
            result.enriched += 1
            result.job_ids.append(job.id)

        await db.commit()

    logger.info(
        "Enrichment: selected=%d enriched=%d short=%d failed=%d paused=%s in %.1fs",
        result.selected, result.enriched, result.skipped_short, result.failed, result.paused,
        time.monotonic() - started,
    )
    return result
