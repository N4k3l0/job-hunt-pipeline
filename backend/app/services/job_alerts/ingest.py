"""Store the jobs from a user's LinkedIn alert emails.

Each LinkedIn job id maps to one job row for everyone (linkedin_jobs). A
job the app already has from another source, by the same link or the
same company, title, city and country, is reused rather than added again.
The email itself is never stored: only the jobs read from it."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.job_alert import JobAlertEmail, JobAlertHit, LinkedInJob
from app.services.job_alerts.linkedin import AlertJob, parse_linkedin_alert
from app.services.parsing.normalizer import (
    compute_canonical_hash,
    derive_country_from_location,
    extract_city,
    get_or_create_source,
)

SOURCE_NAME = "linkedin_alert"
KEY_PREFIX = "jha_"

_US_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
    "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
_CA_PROVINCES = set("AB BC MB NB NL NS NT NU ON PE QC SK YT".split())
_REGION_RE = re.compile(r",\s*([A-Z]{2})$")


def new_alert_key() -> tuple[str, str]:
    """A new key and the hash to store."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_alert_key(key)


def hash_alert_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def country_from_location(location: str | None) -> str | None:
    """ISO country for a LinkedIn location: "United States", "London,
    England, United Kingdom", or "Austin, TX" (US state or Canadian
    province codes)."""
    code = derive_country_from_location(location)
    if code:
        return code
    region = _REGION_RE.search(location or "")
    if region:
        if region.group(1) in _US_STATES:
            return "US"
        if region.group(1) in _CA_PROVINCES:
            return "CA"
    return None


@dataclass
class IngestResult:
    emails_read: int = 0
    emails_already_read: int = 0
    jobs_found: int = 0
    jobs_added: int = 0
    job_ids: list[UUID] = field(default_factory=list)


async def _job_for(db: AsyncSession, source_id: UUID, alert: AlertJob, now: datetime) -> tuple[Job, bool]:
    """The job row for an alert job, and whether it was just added."""
    link = await db.get(LinkedInJob, alert.linkedin_job_id)
    job = await db.get(Job, link.job_id) if link else None
    added = False
    if job is None:
        company = alert.company or "Unknown"
        country = country_from_location(alert.location)
        canonical_hash = compute_canonical_hash(company, alert.title, extract_city(alert.location), country)
        job = (await db.execute(
            select(Job)
            .where(
                or_(Job.job_url == alert.url, Job.canonical_hash == canonical_hash),
                Job.status.notin_(["raw", "duplicate"]),
            )
            .order_by(Job.discovered_at)
            .limit(1)
        )).scalars().first()
        if job is None:
            job = Job(
                source_id=source_id,
                external_id=alert.linkedin_job_id,
                company=company,
                title=alert.title,
                location=alert.location,
                country=country,
                remote_type=alert.remote_type,
                job_url=alert.url,
                salary_text=alert.salary_text,
                salary_min=alert.salary_min,
                salary_max=alert.salary_max,
                salary_currency=alert.salary_currency,
                raw_content=json.dumps({"linkedin_alert": alert.__dict__}),
                canonical_hash=canonical_hash,
                status="enriched",
                parsed_at=now,
            )
            db.add(job)
            await db.flush()
            added = True
        if link is None:
            db.add(LinkedInJob(linkedin_job_id=alert.linkedin_job_id, job_id=job.id))
        else:
            link.job_id = job.id
        await db.flush()
    # LinkedIn listing it means it's open.
    job.last_seen_at = now
    if job.status == "expired":
        job.status = "enriched"
    return job, added


async def ingest_alert_emails(db: AsyncSession, user_id: UUID, messages: list[dict]) -> IngestResult:
    """Read each email once per user and record the jobs it sent them.
    `messages` items: message_id, received_at (datetime or None), html."""
    result = IngestResult()
    now = datetime.now(timezone.utc)
    source = await get_or_create_source(db, SOURCE_NAME, "email")
    seen: set[UUID] = set()

    for message in messages:
        email_id = (await db.execute(
            pg_insert(JobAlertEmail)
            .values(user_id=user_id, message_id=message["message_id"], received_at=message.get("received_at"))
            .on_conflict_do_nothing(constraint="uq_job_alert_emails_user_message")
            .returning(JobAlertEmail.id)
        )).scalar()
        if email_id is None:
            result.emails_already_read += 1
            continue
        result.emails_read += 1

        parsed = parse_linkedin_alert(message.get("html") or "")
        sent_at = message.get("received_at") or now
        for alert in parsed.jobs:
            job, added = await _job_for(db, source.id, alert, now)
            result.jobs_found += 1
            result.jobs_added += int(added)
            await db.execute(
                pg_insert(JobAlertHit)
                .values(
                    user_id=user_id, job_id=job.id, alert_search=parsed.search, alert_location=parsed.location,
                    list_name=alert.list_name, position=alert.position, first_sent_at=sent_at, last_sent_at=sent_at,
                )
                .on_conflict_do_update(
                    constraint="uq_job_alert_hits_user_job",
                    set_={
                        "times_sent": JobAlertHit.times_sent + 1,
                        "last_sent_at": func.greatest(JobAlertHit.last_sent_at, sent_at),
                    },
                )
            )
            if job.id not in seen:
                seen.add(job.id)
                result.job_ids.append(job.id)
        await db.execute(
            JobAlertEmail.__table__.update().where(JobAlertEmail.id == email_id).values(jobs_found=len(parsed.jobs))
        )

    await db.commit()
    return result
