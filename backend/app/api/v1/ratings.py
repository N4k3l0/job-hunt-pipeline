"""Rate matches: the user says whether jobs fit them, and scoring is
measured against it (services/scoring/evaluation.py).

GET    /api/v1/ratings/queue     next jobs to rate, without their scores
PUT    /api/v1/ratings/{job_id}  rate a job good or bad
DELETE /api/v1/ratings/{job_id}  take a rating back
GET    /api/v1/ratings/results   how the current and proposed scoring agree
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import defer, selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.job import Job
from app.models.job_rating import JobRating
from app.services.enrichment.job_enricher import clean_description
from app.services.scoring.evaluation import TARGET_RATINGS, evaluate, rating_queue

router = APIRouter()

DESCRIPTION_CHARS = 1500


class RatingBody(BaseModel):
    rating: Literal["good", "bad"]


def _trimmed(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > 0 else limit].rstrip(",.;:") + "…"


def _job_to_rate(job: Job) -> dict:
    entity = job.entities
    return {
        "id": str(job.id),
        "title": job.title_en or job.title,
        "company": job.company,
        "location": job.location,
        "remote_type": job.remote_type,
        "seniority": job.seniority,
        "employment_type": job.employment_type,
        "salary_text": job.salary_text,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "salary_currency": job.salary_currency,
        "job_url": job.apply_url or job.job_url,
        "posted_at": (job.posted_at or job.discovered_at).isoformat() if (job.posted_at or job.discovered_at) else None,
        "description": _trimmed(clean_description(job.raw_description_en or job.raw_description), DESCRIPTION_CHARS),
        "skills": (entity.skills or [])[:12] if entity else [],
        "requirements": (entity.requirements or [])[:6] if entity else [],
    }


async def _counts(db, user_id) -> dict:
    rows = dict((await db.execute(
        select(JobRating.rating, func.count()).where(JobRating.user_id == user_id).group_by(JobRating.rating)
    )).all())
    return {"rated": sum(rows.values()), "good": rows.get("good", 0), "target": TARGET_RATINGS}


@router.get("/queue")
async def get_queue(user_id: CurrentUserId, db: DbSession, limit: int = Query(10, ge=1, le=50)):
    ids = await rating_queue(db, user_id, limit)
    jobs = {}
    if ids:
        jobs = {
            job.id: job
            for job in (await db.execute(
                select(Job).where(Job.id.in_(ids)).options(defer(Job.raw_content), selectinload(Job.entities))
            )).scalars().all()
        }
    return {
        "jobs": [_job_to_rate(jobs[job_id]) for job_id in ids if job_id in jobs],
        **(await _counts(db, user_id)),
    }


@router.put("/{job_id}")
async def rate_job(job_id: UUID, body: RatingBody, user_id: CurrentUserId, db: DbSession):
    if (await db.get(Job, job_id)) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    stmt = pg_insert(JobRating).values(user_id=user_id, job_id=job_id, rating=body.rating)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_job_ratings_user_job",
        set_={"rating": body.rating, "updated_at": func.now()},
    )
    await db.execute(stmt)
    await db.commit()
    return {"job_id": str(job_id), "rating": body.rating, **(await _counts(db, user_id))}


@router.delete("/{job_id}", status_code=204)
async def unrate_job(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    await db.execute(delete(JobRating).where(JobRating.user_id == user_id, JobRating.job_id == job_id))
    await db.commit()
    return Response(status_code=204)


@router.get("/results")
async def get_results(user_id: CurrentUserId, db: DbSession):
    return await evaluate(db, user_id)
