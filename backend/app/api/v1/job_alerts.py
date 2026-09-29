"""LinkedIn job alert sync.

A Google Apps Script in a Gmail account (written by the Profile page with
the user's key) sends new LinkedIn job alert emails here every 10 minutes.
An admin's script can also carry other users' alerts, forwarded to the
same inbox with their personal address (services/job_alerts/forwarding.py).

POST   /api/v1/job-alerts/linkedin    alert emails, authorized by the user's alert key
GET    /api/v1/job-alerts/status      whether sync is set up, and what it has sent
GET    /api/v1/job-alerts/forwarding  the user's personal forwarding address and Gmail's code
POST   /api/v1/job-alerts/key         a new key (shown once; replaces the old one)
DELETE /api/v1/job-alerts/key         stop accepting the key
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, CurrentUserId, DbSession
from app.models.job_alert import JobAlertEmail, JobAlertHit, JobAlertKey
from app.models.user import User
from app.services.job_alerts import forwarding
from app.services.job_alerts.ingest import KEY_PREFIX, hash_alert_key, ingest_alert_emails, new_alert_key

router = APIRouter()

MAX_MESSAGES = 20
# LinkedIn alert emails are ~90 KB of HTML.
MAX_HTML_CHARS = 1_000_000


class AlertMessage(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    received_at: datetime | None = None
    # "confirmation": Gmail's email asking to confirm a forwarding address.
    kind: Literal["alert", "confirmation"] = "alert"
    html: str = Field(default="", max_length=MAX_HTML_CHARS)
    subject: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=20_000)
    # The addresses it was delivered to (Delivered-To, X-Forwarded-To...):
    # a plus code there says whose forwarded alert it is.
    recipients: list[str] = Field(default_factory=list, max_length=10)


class AlertBatch(BaseModel):
    messages: list[AlertMessage] = Field(max_length=MAX_MESSAGES)
    # The Gmail address the script reads, so users can be shown where to forward.
    inbox: str | None = Field(default=None, max_length=320)


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

    owner = await db.get(User, user_id)
    forwarding.remember_inbox(owner, body.inbox)

    # Whose each email is: the key's owner, or, in an admin's shared inbox,
    # the user whose code it was forwarded to. Only an admin's inbox may
    # carry other users' alerts.
    by_user: dict[UUID, list[dict]] = {}
    unknown = confirmations = 0
    for message in body.messages:
        target = owner
        codes = forwarding.codes_in(message.recipients) if owner.role == "admin" else []
        if codes:
            target = None
            for code in codes:
                target = await forwarding.user_with_code(db, code)
                if target is not None:
                    break
        if target is None:
            unknown += 1
            continue
        if message.kind == "confirmation":
            confirmation = forwarding.read_confirmation(message.subject, message.text)
            if confirmation:
                forwarding.remember_confirmation(target, confirmation)
                confirmations += 1
            continue
        by_user.setdefault(target.id, []).append(message.model_dump(include={"message_id", "received_at", "html"}))
    await db.commit()

    totals = {"emails_read": 0, "emails_already_read": 0, "jobs_found": 0, "jobs_added": 0}
    job_ids: list = []
    for target_id, messages in by_user.items():
        result = await ingest_alert_emails(db, target_id, messages)
        for name in totals:
            totals[name] += getattr(result, name)
        job_ids += [j for j in result.job_ids if j not in job_ids]
    # New jobs need scores, and ones the app already had may not be scored for everyone yet.
    await rescore_jobs_for_all_users(job_ids)
    return {**totals, "users": len(by_user), "confirmations": confirmations, "not_for_anyone": unknown}


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


@router.get("/forwarding")
async def forwarding_details(user: CurrentUser, db: DbSession):
    """Where the user forwards their LinkedIn alerts, once an admin's script
    reads a shared inbox, and the code Gmail sent to confirm it."""
    inbox = await forwarding.shared_inbox(db)
    if inbox is None:
        return {"ready": False, "address": None, "inbox_owner": False, "confirmation": None}
    address, admin = inbox
    code = await forwarding.ensure_code(db, user)
    return {
        "ready": True,
        "address": forwarding.personal_address(address, code),
        "inbox_owner": admin.id == user.id,
        "confirmation": (user.preferences or {}).get(forwarding.CONFIRMATION_KEY),
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
