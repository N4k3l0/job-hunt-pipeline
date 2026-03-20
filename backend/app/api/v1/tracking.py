from uuid import UUID
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.tracking import ApplicationTracking, PipelineEvent
from app.models.job import Job

router = APIRouter()

VALID_TRANSITIONS = {
    "approved": ["applied"],
    "applied": ["follow_up_due", "interviewing", "rejected", "ghosted", "archived"],
    "follow_up_due": ["applied", "interviewing", "rejected", "ghosted", "archived"],
    "interviewing": ["offered", "rejected", "ghosted", "archived"],
    "offered": ["archived"],
    "rejected": ["archived"],
    "ghosted": ["archived"],
}


class StatusUpdate(BaseModel):
    status: str
    notes: str | None = None
    follow_up_date: date | None = None


@router.get("")
async def get_pipeline(user_id: CurrentUserId, db: DbSession):
    """Get the application pipeline (all tracked applications)."""
    result = await db.execute(
        select(ApplicationTracking)
        .where(ApplicationTracking.user_id == user_id)
        .options(selectinload(ApplicationTracking.job))
        .order_by(ApplicationTracking.updated_at.desc())
    )
    trackings = result.scalars().all()

    return [
        {
            "id": str(t.id),
            "job_id": str(t.job_id),
            "status": t.status,
            "applied_at": t.applied_at.isoformat() if t.applied_at else None,
            "follow_up_date": str(t.follow_up_date) if t.follow_up_date else None,
            "notes": t.notes,
            "created_at": t.created_at.isoformat(),
            "job": {
                "title": t.job.title,
                "company": t.job.company,
                "location": t.job.location,
            } if t.job else None,
        }
        for t in trackings
    ]


@router.put("/{tracking_id}/status")
async def update_status(
    tracking_id: UUID,
    update: StatusUpdate,
    user_id: CurrentUserId,
    db: DbSession,
):
    """Update the status of a tracked application with state machine validation."""
    result = await db.execute(
        select(ApplicationTracking).where(
            ApplicationTracking.id == tracking_id,
            ApplicationTracking.user_id == user_id,
        )
    )
    tracking = result.scalar_one_or_none()
    if not tracking:
        raise HTTPException(status_code=404, detail="Tracking entry not found")

    # Validate transition
    allowed = VALID_TRANSITIONS.get(tracking.status, [])
    if update.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{tracking.status}' to '{update.status}'. Allowed: {allowed}",
        )

    old_status = tracking.status
    tracking.status = update.status

    if update.notes:
        tracking.notes = update.notes
    if update.follow_up_date:
        tracking.follow_up_date = update.follow_up_date
    if update.status == "applied":
        tracking.applied_at = datetime.now(timezone.utc)

    # Log the event
    event = PipelineEvent(
        job_id=tracking.job_id,
        user_id=user_id,
        event_type="status_change",
        payload={"from": old_status, "to": update.status, "notes": update.notes},
    )
    db.add(event)

    await db.commit()
    return {"status": update.status, "tracking_id": str(tracking_id)}


@router.get("/reminders")
async def get_reminders(user_id: CurrentUserId, db: DbSession):
    """Get all due follow-up reminders."""
    today = date.today()
    result = await db.execute(
        select(ApplicationTracking)
        .where(
            ApplicationTracking.user_id == user_id,
            ApplicationTracking.follow_up_date <= today,
            ApplicationTracking.status.notin_(["rejected", "ghosted", "archived"]),
        )
        .options(selectinload(ApplicationTracking.job))
        .order_by(ApplicationTracking.follow_up_date)
    )
    trackings = result.scalars().all()

    return [
        {
            "id": str(t.id),
            "job_id": str(t.job_id),
            "status": t.status,
            "follow_up_date": str(t.follow_up_date),
            "notes": t.notes,
            "job": {
                "title": t.job.title,
                "company": t.job.company,
            } if t.job else None,
        }
        for t in trackings
    ]
