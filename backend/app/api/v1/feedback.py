"""Feedback endpoints.

POST /api/v1/feedback   — any signed-in user submits a feedback item
GET  /api/v1/feedback   — admin lists all feedback (most recent first)
PATCH /api/v1/feedback/{id} — admin marks resolved / unresolved
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from app.api.deps import CurrentUserId, AdminUser, DbSession
from app.models.feedback import Feedback


router = APIRouter()


class FeedbackCreate(BaseModel):
    category: str = Field(default="general")
    message: str = Field(..., min_length=4, max_length=8000)
    context: str | None = Field(default=None, max_length=4000)


class FeedbackResponse(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str | None = None
    user_email: str | None = None
    category: str
    message: str
    context: str | None
    resolved: bool
    created_at: str

    model_config = {"from_attributes": True}


class FeedbackUpdate(BaseModel):
    resolved: bool


_VALID_CATEGORIES = {"bug", "feature", "general"}


@router.post("", response_model=dict)
async def submit_feedback(
    body: FeedbackCreate,
    user_id: CurrentUserId,
    db: DbSession,
):
    """Any signed-in user can submit feedback. Stored against their
    user_id so admins can follow up if needed."""
    category = body.category.strip().lower()
    if category not in _VALID_CATEGORIES:
        category = "general"

    row = Feedback(
        user_id=user_id,
        category=category,
        message=body.message.strip(),
        context=(body.context.strip() if body.context else None),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": str(row.id), "status": "received"}


@router.get("", response_model=list[FeedbackResponse])
async def list_feedback(
    admin: AdminUser,
    db: DbSession,
    resolved: bool | None = None,
    limit: int = 200,
):
    """Admin reads every feedback item. Filter by resolved=true/false
    to triage. Newest first."""
    q = select(Feedback).order_by(desc(Feedback.created_at)).limit(min(limit, 500))
    if resolved is not None:
        q = q.where(Feedback.resolved == resolved)
    rows = (await db.execute(q)).scalars().all()

    # Hydrate user_name / user_email in a single follow-up query.
    from app.models.user import User
    user_ids = {r.user_id for r in rows}
    name_map: dict[UUID, tuple[str, str]] = {}
    if user_ids:
        user_rows = await db.execute(
            select(User.id, User.name, User.email).where(User.id.in_(user_ids))
        )
        for uid, name, email in user_rows.all():
            name_map[uid] = (name, email)

    out: list[FeedbackResponse] = []
    for r in rows:
        name, email = name_map.get(r.user_id, (None, None))
        out.append(FeedbackResponse(
            id=r.id,
            user_id=r.user_id,
            user_name=name,
            user_email=email,
            category=r.category,
            message=r.message,
            context=r.context,
            resolved=r.resolved,
            created_at=r.created_at.isoformat() if r.created_at else "",
        ))
    return out


@router.patch("/{feedback_id}")
async def update_feedback(
    feedback_id: UUID,
    body: FeedbackUpdate,
    admin: AdminUser,
    db: DbSession,
):
    """Admin marks an item resolved (or unresolved if they reopen it)."""
    row = (await db.execute(
        select(Feedback).where(Feedback.id == feedback_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    row.resolved = body.resolved
    await db.commit()
    return {"id": str(row.id), "resolved": row.resolved}
