from fastapi import APIRouter

from app.api.deps import CurrentUserId, DbSession

router = APIRouter()


@router.post("/run/{job_id}")
async def score_job(job_id: str, user_id: CurrentUserId, db: DbSession):
    """Score a single job for the current user."""
    # TODO: Queue scoring task
    return {"status": "queued", "job_id": job_id}


@router.post("/batch")
async def batch_score(user_id: CurrentUserId, db: DbSession):
    """Score all unscored jobs for the current user."""
    # TODO: Queue batch scoring task
    return {"status": "queued"}


@router.get("/{job_id}")
async def get_score(job_id: str, user_id: CurrentUserId, db: DbSession):
    """Get the score breakdown for a job."""
    # TODO: Implement
    return {"job_id": job_id, "score": None}
