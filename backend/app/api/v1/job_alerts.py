"""LinkedIn job alert sync.

A Google Apps Script in the user's own Gmail (written by the Profile page
with the user's key) sends new LinkedIn job alert emails here every hour.

POST   /api/v1/job-alerts/linkedin  alert emails, authorized by the user's alert key
GET    /api/v1/job-alerts/status    whether sync is set up, and what it has sent
POST   /api/v1/job-alerts/key       a new key (shown once; replaces the old one)
DELETE /api/v1/job-alerts/key       stop accepting the key
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUserId, DbSession
from app.models.job_alert import JobAlertEmail, JobAlertHit, JobAlertKey
from app.services.job_alerts.ingest import KEY_PREFIX, hash_alert_key, ingest_alert_emails, new_alert_key

router = APIRouter()

MAX_MESSAGES = 20
# LinkedIn alert emails are ~90 KB of HTML.
MAX_HTML_CHARS = 1_000_000


class AlertMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    received_at: datetime | None = None
    html: str = Field(max_length=MAX_HTML_CHARS)


class AlertBatch(BaseModel):
    messages: list[AlertMessage] = Field(max_length=MAX_MESSAGES)


async def alert_key_user_id(db: DbSession, authorization: str | None = Header(None)) -> UUID:
    """The user whose alert key the request carries."""
    key = (authorization or "").removeprefix("Bearer ").strip()
    if not key.startswith(KEY_PREFIX):
        raise HTTPException(status_code=401, detail="Send your job alert key as 'Authorization: Bearer <key>'")
    row = (await db.execute(
        select(JobAlertKey).where(JobAlertKey.key_hash == hash_alert_key(key))
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="This job alert key isn't valid. Create a new one on your Profile.")
    row.last_used_at = datetime.now(timezone.utc)
    return row.user_id


@router.post("/linkedin")
async def receive_linkedin_alerts(
    body: AlertBatch,
    db: DbSession,
    user_id: Annotated[UUID, Depends(alert_key_user_id)],
):
    from app.workers.scoring_tasks import rescore_jobs_for_all_users

    result = await ingest_alert_emails(db, user_id, [m.model_dump() for m in body.messages])
    # New jobs need scores, and ones the app already had may not be scored for everyone yet.
    await rescore_jobs_for_all_users(result.job_ids)
    return {
        "emails_read": result.emails_read,
        "emails_already_read": result.emails_already_read,
        "jobs_found": result.jobs_found,
        "jobs_added": result.jobs_added,
    }


@router.get("/status")
async def alert_sync_status(user_id: CurrentUserId, db: DbSession):
    key = await db.get(JobAlertKey, user_id)
    emails = (await db.execute(
        select(func.count(JobAlertEmail.id), func.max(JobAlertEmail.received_at)).where(JobAlertEmail.user_id == user_id)
    )).one()
    jobs_sent = (await db.execute(
        select(func.count(JobAlertHit.id)).where(JobAlertHit.user_id == user_id)
    )).scalar() or 0
    searches = (await db.execute(
        select(JobAlertHit.alert_search, JobAlertHit.alert_location, func.count(JobAlertHit.id))
        .where(JobAlertHit.user_id == user_id, JobAlertHit.alert_search.is_not(None))
        .group_by(JobAlertHit.alert_search, JobAlertHit.alert_location)
        .order_by(func.count(JobAlertHit.id).desc())
        .limit(5)
    )).all()
    return {
        "has_key": key is not None,
        "key_created_at": key.created_at.isoformat() if key and key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key and key.last_used_at else None,
        "emails_read": emails[0] or 0,
        "last_email_at": emails[1].isoformat() if emails[1] else None,
        "jobs_sent": jobs_sent,
        "searches": [{"search": s, "location": loc, "jobs": n} for s, loc, n in searches],
    }


@router.post("/key")
async def create_alert_key(user_id: CurrentUserId, db: DbSession):
    key, key_hash = new_alert_key()
    await db.execute(
        pg_insert(JobAlertKey)
        .values(user_id=user_id, key_hash=key_hash)
        .on_conflict_do_update(
            index_elements=[JobAlertKey.user_id],
            set_={"key_hash": key_hash, "created_at": func.now(), "last_used_at": None},
        )
    )
    await db.commit()
    return {"key": key}


@router.delete("/key", status_code=204)
async def delete_alert_key(user_id: CurrentUserId, db: DbSession):
    await db.execute(delete(JobAlertKey).where(JobAlertKey.user_id == user_id))
    await db.commit()
    return Response(status_code=204)
