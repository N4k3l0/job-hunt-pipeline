"""The message step after applying: who to write to, and a note to send
them from the user's own LinkedIn (services/outreach/message.py)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import CurrentUserId, DbSession
from app.models.job import Job
from app.services.outreach.message import NotSentYet, prepare_note, update_note, view

router = APIRouter()


class PrepareBody(BaseModel):
    # Look for someone else and write the note again (another lookup).
    look_again: bool = False


class NoteUpdate(BaseModel):
    message: str | None = Field(default=None, max_length=2000)
    status: Literal["drafted", "sent", "skipped"] | None = None


async def _job(db, job_id: UUID) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}")
async def get_note(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    await _job(db, job_id)
    return await view(db, user_id, job_id)


@router.post("/{job_id}/prepare")
async def prepare(job_id: UUID, user_id: CurrentUserId, db: DbSession, body: PrepareBody | None = None):
    """Find the person to write to and write the note (about a minute)."""
    await _job(db, job_id)
    try:
        await prepare_note(db, user_id, job_id, look_again=bool(body and body.look_again))
    except NotSentYet as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return await view(db, user_id, job_id)


@router.put("/{job_id}")
async def save(job_id: UUID, body: NoteUpdate, user_id: CurrentUserId, db: DbSession):
    """Save edits to the note, or mark it sent, skipped, or not sent after all."""
    await _job(db, job_id)
    try:
        await update_note(db, user_id, job_id, message=body.message, status=body.status)
    except NotSentYet as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return await view(db, user_id, job_id)
