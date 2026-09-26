"""Keep the jobs we have in step with the company boards that list them.

The curated source reads each company's whole board every day. Only the
first PER_COMPANY_CAP of each board are added as new jobs, but every
listing on a board that answered says a job we already have is still
open. Before this, a company with more than 30 open jobs (Anthropic lists
600+) looked like it had taken down everything past its first 30, and
job_expiry closed those jobs as gone from the board.

For each job we have whose link is on a board today:
- last_seen_at moves to now (it's still open);
- a new title is taken up: companies rename jobs, and a renamed job no
  longer matched by title, so it looked closed;
- a job we closed is opened again: its company still lists it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from app.core.database import create_worker_session
from app.models.job import Job
from app.services.parsing.normalizer import (
    compute_canonical_hash,
    extract_city,
    normalize_country,
    normalize_url,
)

# Renamed jobs are rescored here, so a run renames at most this many (a
# company renaming everything at once) and leaves the rest for the next.
MAX_RENAMED = 200


def _clean(title: str | None) -> str:
    return " ".join((title or "").split())


async def refresh_from_boards(listed: dict[str, str], now: datetime | None = None) -> dict:
    """`listed` maps each listing's normalized URL to its title."""
    outcome = {"listed": len(listed), "still_listed": 0, "renamed": 0, "reopened": 0, "scores_updated": 0}
    if not listed:
        return outcome
    now = now or datetime.now(timezone.utc)

    async with create_worker_session()() as db:
        rows = (await db.execute(
            select(Job.id, Job.job_url, Job.title, Job.status, Job.company, Job.location, Job.country)
            .where(Job.job_url.isnot(None), Job.status.notin_(["raw", "duplicate"]))
        )).all()

        seen, reopened, renamed = [], [], []
        for job_id, url, title, status, company, location, country in rows:
            key = normalize_url(url)
            if key not in listed:
                continue
            seen.append(job_id)
            if status == "expired":
                reopened.append(job_id)
            new_title = _clean(listed[key])
            if new_title and new_title != _clean(title):
                renamed.append((job_id, new_title, compute_canonical_hash(
                    company or "", new_title, extract_city(location), normalize_country(country),
                )))

        for start in range(0, len(seen), 1000):
            await db.execute(
                update(Job).where(Job.id.in_(seen[start:start + 1000])).values(last_seen_at=now)
                .execution_options(synchronize_session=False)
            )
        for start in range(0, len(reopened), 1000):
            await db.execute(
                update(Job).where(Job.id.in_(reopened[start:start + 1000]), Job.status == "expired")
                .values(status="scored").execution_options(synchronize_session=False)
            )
        renamed = renamed[:MAX_RENAMED]
        for job_id, title, canonical_hash in renamed:
            # title_en was a translation of the old title.
            await db.execute(
                update(Job).where(Job.id == job_id)
                .values(title=title, title_en=None, canonical_hash=canonical_hash)
                .execution_options(synchronize_session=False)
            )
        await db.commit()

    if renamed:
        from app.workers.scoring_tasks import rescore_jobs_for_all_users
        outcome["scores_updated"] = await rescore_jobs_for_all_users([r[0] for r in renamed])
    outcome.update(still_listed=len(seen), renamed=len(renamed), reopened=len(reopened))
    return outcome
