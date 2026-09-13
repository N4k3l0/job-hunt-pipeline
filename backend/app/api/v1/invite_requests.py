"""Invite requests from the public landing page.

POST /api/v1/invite-requests — anyone (no auth) submits an email
GET  /api/v1/invite-requests — admin lists them, newest first
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select, desc
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import AdminUser, DbSession
from app.models.invite_request import InviteRequest


router = APIRouter()


class InviteRequestCreate(BaseModel):
    email: EmailStr = Field(..., max_length=320)
    source: str | None = Field(default=None, max_length=50)

    @field_validator("email")
    @classmethod
    def _lowercase(cls, v: str) -> str:
        return v.strip().lower()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_invite_request(body: InviteRequestCreate, db: DbSession):
    """Save an invite request. Repeat submissions of the same email are
    accepted silently, so the response never reveals who already asked."""
    stmt = (
        pg_insert(InviteRequest)
        .values(email=body.email, source=body.source)
        .on_conflict_do_nothing(index_elements=["email"])
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "received"}


@router.get("")
async def list_invite_requests(admin: AdminUser, db: DbSession):
    rows = (await db.execute(
        select(InviteRequest).order_by(desc(InviteRequest.created_at)).limit(500)
    )).scalars().all()
    return [
        {
            "id": str(r.id),
            "email": r.email,
            "source": r.source,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
