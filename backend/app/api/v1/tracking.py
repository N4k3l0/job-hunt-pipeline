from uuid import UUID
from datetime import date, datetime, timedelta, timezone

DEFAULT_FOLLOW_UP_DAYS = 7

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, CurrentUserId, DbSession
from app.models.tracking import ApplicationTracking, PipelineEvent
from app.services.job_freshness import closed_note
from app.services.outreach.message import notes_for

router = APIRouter()

VALID_TRANSITIONS = {
    "approved": ["applied"],
    "applied": ["follow_up_due", "interviewing", "rejected", "ghosted", "archived"],
    "follow_up_due": ["applied", "interviewing", "rejected", "ghosted", "archived"],
    "interviewing": ["offered", "rejected", "ghosted", "archived"],
    "offered": ["archived"],
    "rejected": ["archived"],
    # A reply after all: back to waiting, or straight to what happened.
    "ghosted": ["applied", "interviewing", "rejected", "archived"],
}


# Cards the user cleared off the Closed column of the Applications board:
# hidden there, never deleted, so the history still counts (the app won't
# offer a job again that they were turned down for).
CLEARED_KEY = "cleared_from_board"
CLEARED_MAX = 2000


class Cards(BaseModel):
    ids: list[UUID] = Field(max_length=500)


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
    notes = await notes_for(db, user_id, [t.job_id for t in trackings])

    return [
        {
            "id": str(t.id),
            "job_id": str(t.job_id),
            "status": t.status,
            # The note to someone at the company: drafted, sent, skipped or None.
            "message": notes[t.job_id].status if t.job_id in notes else None,
            "applied_at": t.applied_at.isoformat() if t.applied_at else None,
            "follow_up_date": str(t.follow_up_date) if t.follow_up_date else None,
            "notes": t.notes,
            "created_at": t.created_at.isoformat(),
            "job": {
                "title": t.job.title,
                "company": t.job.company,
                "location": t.job.location,
                "closed_note": closed_note(t.job),
                "closed": t.job.status == "expired",
            } if t.job else None,
        }
        for t in trackings
    ]


@router.get("/cleared")
async def get_cleared(user: CurrentUser):
    """The cards cleared off the Closed column."""
    return {"ids": (user.preferences or {}).get(CLEARED_KEY, [])}


@router.post("/cleared")
async def clear_cards(body: Cards, user: CurrentUser, db: DbSession):
    """Take cards off the Closed column. Nothing is deleted."""
    cleared = (user.preferences or {}).get(CLEARED_KEY, [])
    new = [str(i) for i in body.ids if str(i) not in cleared]
    cleared = (cleared + new)[-CLEARED_MAX:]
    # A new dict, so the change to the JSON column is saved.
    user.preferences = {**(user.preferences or {}), CLEARED_KEY: cleared}
    await db.commit()
    return {"ids": cleared}


@router.post("/cleared/restore")
async def restore_cards(body: Cards, user: CurrentUser, db: DbSession):
    """Put cleared cards back on the Closed column (Undo)."""
    back = {str(i) for i in body.ids}
    cleared = [i for i in (user.preferences or {}).get(CLEARED_KEY, []) if i not in back]
    user.preferences = {**(user.preferences or {}), CLEARED_KEY: cleared}
    await db.commit()
    return {"ids": cleared}


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
        # Default a follow-up reminder 7 days out so the inbox surfaces it later.
        if not update.follow_up_date and not tracking.follow_up_date:
            tracking.follow_up_date = date.today() + timedelta(days=DEFAULT_FOLLOW_UP_DAYS)

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
    notes = await notes_for(db, user_id, [t.job_id for t in trackings])

    return [
        {
            "id": str(t.id),
            "job_id": str(t.job_id),
            "status": t.status,
            # The note to someone at the company: drafted, sent, skipped or None.
            "message": notes[t.job_id].status if t.job_id in notes else None,
            "follow_up_date": str(t.follow_up_date),
            "notes": t.notes,
            "job": {
                "title": t.job.title,
                "company": t.job.company,
            } if t.job else None,
        }
        for t in trackings
    ]
