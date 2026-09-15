"""Measure scoring against what the user says about jobs.

The Rate matches page asks the user whether jobs fit them, without showing
scores. Their ratings are then compared with the scores the current
version (SCORE_VERSION) and the proposed one (PROPOSED_SCORE_VERSION) give
the same jobs, both computed live from the same job and profile data, so a
scoring change is judged on the user's own verdicts before it replaces the
stored scores.

Which jobs to rate: the 20 best-scored inbox jobs, 20 more from the rest of
the inbox, 10 that just miss it (scores 35-49) and 10 the user's LinkedIn
job alerts sent. A mix is needed to see good jobs the scores leave out,
not only bad jobs at the top. The order is shuffled so the top matches
don't come first.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import defer, selectinload

from app.models.job import Job, JobEntity, JobSource
from app.models.job_rating import JobRating
from app.models.job_alert import JobAlertHit
from app.models.job_state import UserJobState
from app.models.scoring import JobScore
from app.models.tracking import ApplicationTracking
from app.services.job_state import APPLIED_TRACKING_STATUSES
from app.services.jobs_filter import apply_user_filters, job_group_key, user_filter_kwargs
from app.services.scoring.scorer import PROPOSED_SCORE_VERSION, SCORE_VERSION, compute_job_score

TARGET_RATINGS = 50
# Fewer ratings than this don't say much; the page asks for more first.
MIN_RATINGS_FOR_RESULTS = 20
INBOX_MIN_SCORE = 50
NEAR_MIN_SCORE = 35
TOP_SAMPLE = 20
INBOX_SAMPLE = 20
NEAR_SAMPLE = 10
# Jobs the user's LinkedIn alerts sent, whatever their score, so ratings
# show how often LinkedIn's picks fit.
ALERT_SAMPLE = 10
TOP_N = 10
DISAGREEMENTS = 5


def ranking_metrics(scored: list[tuple[float, bool]]) -> dict:
    """How well scores agree with ratings. `scored` is (score, rated good)
    per job.

    - ranking_accuracy: the share of (good, not good) pairs where the good
      job scores higher, ties counting half. 0.5 is a coin flip.
    - top: good jobs among the TOP_N highest scores.
    - inbox: good jobs among those scoring INBOX_MIN_SCORE or more.
    - missed_good: good jobs scoring below it.
    """
    good = [s for s, is_good in scored if is_good]
    bad = [s for s, is_good in scored if not is_good]
    pairs = len(good) * len(bad)
    accuracy = None
    if pairs:
        wins = sum(1.0 if g > b else 0.5 if g == b else 0.0 for g in good for b in bad)
        accuracy = round(wins / pairs, 3)
    top = sorted(scored, key=lambda item: item[0], reverse=True)[:TOP_N]
    inbox = [is_good for s, is_good in scored if s >= INBOX_MIN_SCORE]
    return {
        "rated": len(scored),
        "good": len(good),
        "ranking_accuracy": accuracy,
        "top": {"size": len(top), "good": sum(1 for _, is_good in top if is_good)},
        "inbox": {"size": len(inbox), "good": sum(inbox)},
        "missed_good": sum(1 for s in good if s < INBOX_MIN_SCORE),
    }


def _shuffle_key(user_id: UUID, job_id: UUID) -> str:
    return hashlib.sha256(f"{user_id}:{job_id}".encode()).hexdigest()


async def _candidate_jobs(db, user_id: UUID) -> list[tuple[UUID, float]]:
    """The user's jobs scoring NEAR_MIN_SCORE or more that pass their inbox
    filters, one posting per job, best score first."""
    applied = exists().where(
        ApplicationTracking.job_id == Job.id,
        ApplicationTracking.user_id == user_id,
        ApplicationTracking.status.in_(APPLIED_TRACKING_STATUSES),
    )
    query = (
        select(Job.id, JobScore.overall_fit, *job_group_key(Job))
        .join(JobScore, and_(JobScore.job_id == Job.id, JobScore.user_id == user_id))
        .outerjoin(JobSource, JobSource.id == Job.source_id)
        .outerjoin(JobEntity, JobEntity.job_id == Job.id)
        .outerjoin(UserJobState, and_(UserJobState.job_id == Job.id, UserJobState.user_id == user_id))
        .where(
            Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]),
            or_(UserJobState.status.is_(None), UserJobState.status != "dismissed"),
            JobScore.overall_fit >= NEAR_MIN_SCORE,
            ~applied,
        )
    )
    query = apply_user_filters(query, **(await user_filter_kwargs(db, user_id)))
    rows = (await db.execute(query.order_by(JobScore.overall_fit.desc(), Job.id))).all()
    seen: set[tuple] = set()
    out: list[tuple[UUID, float]] = []
    for job_id, fit, company_key, title_key in rows:
        if (company_key, title_key) in seen:
            continue
        seen.add((company_key, title_key))
        out.append((job_id, fit))
    return out


async def rating_queue(db, user_id: UUID, limit: int) -> list[UUID]:
    """Ids of the next jobs to rate: the sample first, then any other
    candidate, in a fixed shuffled order."""
    candidates = await _candidate_jobs(db, user_id)
    rated = set((await db.execute(
        select(JobRating.job_id).where(JobRating.user_id == user_id)
    )).scalars().all())

    def shuffled(rows):
        return sorted(rows, key=lambda row: _shuffle_key(user_id, row[0]))

    top = candidates[:TOP_SAMPLE]
    rest = candidates[TOP_SAMPLE:]
    inbox = shuffled([r for r in rest if r[1] >= INBOX_MIN_SCORE])[:INBOX_SAMPLE]
    near = shuffled([r for r in rest if r[1] < INBOX_MIN_SCORE])[:NEAR_SAMPLE]
    picked = {r[0] for r in top + inbox + near}
    alert_rows = (await db.execute(
        select(JobAlertHit.job_id)
        .join(Job, Job.id == JobAlertHit.job_id)
        .outerjoin(UserJobState, and_(UserJobState.job_id == Job.id, UserJobState.user_id == user_id))
        .where(
            JobAlertHit.user_id == user_id,
            Job.status.notin_(["duplicate", "raw", "expired", "dismissed"]),
            or_(UserJobState.status.is_(None), UserJobState.status != "dismissed"),
        )
    )).scalars().all()
    alerts = shuffled([(job_id, None) for job_id in alert_rows if job_id not in picked and job_id not in rated])
    sample = shuffled(top + inbox + near + alerts[:ALERT_SAMPLE])
    in_sample = {r[0] for r in sample}
    ordered = sample + shuffled([r for r in candidates if r[0] not in in_sample])
    return [job_id for job_id, _ in ordered if job_id not in rated][:limit]


async def evaluate(db, user_id: UUID) -> dict:
    """Metrics for the current and the proposed scoring on the user's rated
    jobs, and the rated jobs the proposed scoring disagrees with most."""
    from app.workers.scoring_tasks import job_score_inputs, load_scoring_profile

    ratings = dict((await db.execute(
        select(JobRating.job_id, JobRating.rating).where(JobRating.user_id == user_id)
    )).all())
    alert_job_ids = set((await db.execute(
        select(JobAlertHit.job_id).where(JobAlertHit.user_id == user_id)
    )).scalars().all())
    profile = await load_scoring_profile(db, str(user_id))
    versions = [SCORE_VERSION] + ([PROPOSED_SCORE_VERSION] if PROPOSED_SCORE_VERSION != SCORE_VERSION else [])
    rows: list[dict] = []
    if ratings and profile:
        jobs = (await db.execute(
            select(Job)
            .where(Job.id.in_(list(ratings)))
            .order_by(Job.id)
            .options(defer(Job.raw_content), selectinload(Job.entities))
        )).scalars().all()
        for job in jobs:
            job_data, job_entities = job_score_inputs(job)
            rows.append({
                "job_id": str(job.id),
                "title": job.title_en or job.title,
                "company": job.company,
                "rating": ratings[job.id],
                "linkedin_alert": job.id in alert_job_ids,
                "scores": {
                    str(v): compute_job_score(job_data, job_entities, profile, version=v)["overall_fit"]
                    for v in versions
                },
            })

    def metrics(version: int) -> dict:
        return {
            "version": version,
            **ranking_metrics([(r["scores"][str(version)], r["rating"] == "good") for r in rows]),
        }

    # Where the newest scoring disagrees: good jobs it keeps out of the inbox
    # and not-good ones it lets in.
    latest = str(versions[-1])
    good_scored_low = sorted(
        (r for r in rows if r["rating"] == "good" and r["scores"][latest] < INBOX_MIN_SCORE),
        key=lambda r: r["scores"][latest],
    )
    bad_scored_high = sorted(
        (r for r in rows if r["rating"] == "bad" and r["scores"][latest] >= INBOX_MIN_SCORE),
        key=lambda r: -r["scores"][latest],
    )
    return {
        "rated": len(rows),
        "good": sum(1 for r in rows if r["rating"] == "good"),
        "target": TARGET_RATINGS,
        "min_for_results": MIN_RATINGS_FOR_RESULTS,
        "current": metrics(SCORE_VERSION),
        "proposed": metrics(PROPOSED_SCORE_VERSION) if len(versions) > 1 else None,
        # How often the user rates jobs their LinkedIn alerts sent as good,
        # next to every other rated job.
        "linkedin_alerts": {
            "rated": sum(1 for r in rows if r["linkedin_alert"]),
            "good": sum(1 for r in rows if r["linkedin_alert"] and r["rating"] == "good"),
            "others_rated": sum(1 for r in rows if not r["linkedin_alert"]),
            "others_good": sum(1 for r in rows if not r["linkedin_alert"] and r["rating"] == "good"),
        },
        "disagreements": {
            "good_scored_low": good_scored_low[:DISAGREEMENTS],
            "bad_scored_high": bad_scored_high[:DISAGREEMENTS],
        },
    }
