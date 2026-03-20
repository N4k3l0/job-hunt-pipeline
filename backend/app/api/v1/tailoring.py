from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.tailoring import TailoredApplication
from app.models.job import Job
from app.schemas.job import TailoredApplicationResponse, TailoredApplicationUpdate

router = APIRouter()


@router.post("/generate/{job_id}")
async def generate_tailored_materials(
    job_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Trigger the tailoring pipeline for a job."""
    # Verify job exists
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    if not job_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if already generating
    existing = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.job_id == job_id,
            TailoredApplication.user_id == user_id,
            TailoredApplication.approval_status.in_(["pending", "generating"]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tailoring already in progress for this job")

    from app.workers.tailoring_tasks import generate_tailored_application
    generate_tailored_application.delay(str(job_id), str(user_id))
    return {"status": "queued", "job_id": str(job_id)}


@router.get("/queue")
async def get_review_queue(user_id: CurrentUserId, db: DbSession):
    """Get all tailored applications pending review, with job details."""
    result = await db.execute(
        select(TailoredApplication)
        .where(
            TailoredApplication.user_id == user_id,
            TailoredApplication.approval_status.in_(["ready", "generating"]),
        )
        .options(selectinload(TailoredApplication.job))
        .order_by(TailoredApplication.created_at.desc())
    )
    apps = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "job_id": str(a.job_id),
            "tailored_summary": a.tailored_summary,
            "cover_letter": a.cover_letter,
            "recruiter_message": a.recruiter_message,
            "short_answers": a.short_answers,
            "keyword_matches": a.keyword_matches,
            "validation_notes": a.validation_notes,
            "approval_status": a.approval_status,
            "tailored_resume_url": a.tailored_resume_url,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            "job": {
                "title": a.job.title,
                "company": a.job.company,
                "location": a.job.location,
                "country": a.job.country,
                "remote_type": a.job.remote_type,
                "job_url": a.job.job_url,
                "apply_url": a.job.apply_url,
                "salary_text": a.job.salary_text,
            } if a.job else None,
        }
        for a in apps
    ]


@router.get("/{tailored_id}", response_model=TailoredApplicationResponse)
async def get_tailored_application(
    tailored_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Get a tailored application's full details."""
    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")
    return app


@router.put("/{tailored_id}", response_model=TailoredApplicationResponse)
async def update_tailored_application(
    tailored_id: UUID,
    data: TailoredApplicationUpdate,
    user_id: CurrentUserId,
    db: DbSession,
):
    """Edit tailored content before approval."""
    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")

    if app.approval_status == "approved":
        raise HTTPException(status_code=400, detail="Cannot edit approved applications")

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(app, field, value)

    await db.commit()
    await db.refresh(app)
    return app


@router.post("/{tailored_id}/approve", response_model=TailoredApplicationResponse)
async def approve_application(
    tailored_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Approve and lock a tailored application pack."""
    from datetime import datetime, timezone

    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")

    if app.approval_status == "approved":
        raise HTTPException(status_code=400, detail="Already approved")

    app.approval_status = "approved"
    app.approved_at = datetime.now(timezone.utc)

    # Create tracking entry
    from app.models.tracking import ApplicationTracking
    tracking = ApplicationTracking(
        job_id=app.job_id,
        user_id=user_id,
        tailored_application_id=app.id,
        status="approved",
    )
    db.add(tracking)

    await db.commit()
    await db.refresh(app)
    return app


@router.delete("/{tailored_id}")
async def delete_tailored_application(
    tailored_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Delete a tailored application from the review queue."""
    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")

    await db.delete(app)
    await db.commit()
    return {"status": "deleted", "id": str(tailored_id)}


@router.get("/{tailored_id}/pdf")
async def download_pdf(tailored_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Download the tailored resume as PDF."""
    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")
    if not app.tailored_resume_url:
        raise HTTPException(status_code=404, detail="PDF not yet generated")

    return RedirectResponse(url=app.tailored_resume_url)
