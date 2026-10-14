"""The daily email: settings, preview, a test send, and unsubscribe.

GET  /api/v1/notifications/settings     whether the user gets it, and whether email is set up
PUT  /api/v1/notifications/settings     turn it on or off
GET  /api/v1/notifications/digest/preview   today's email for the user, not sent
POST /api/v1/notifications/digest/test      send today's email to the user now
GET  /api/v1/notifications/unsubscribe      the email's "stop these emails" link (no login)
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.models.user import User
from app.services.notifications.digest import (
    EVERYONE_KEY, TEST_KEY, everyone_gets_it, todays_email, unsubscribe_url, valid_unsubscribe_token,
)
from app.services.notifications.email import (
    EmailFailed, EmailNotConfigured, email_configured, frontend_url, send_email,
)

router = APIRouter()


class NotificationSettings(BaseModel):
    daily_email: bool | None = None
    # Admins only: send the daily email to every user, not just admins.
    everyone: bool | None = None


async def _settings(db, user: User) -> dict:
    from app.services.job_alerts.forwarding import shared_inbox

    inbox = await shared_inbox(db)
    body = {
        "daily_email": user.email_digest,
        "email": user.email,
        # Either an email service, or the admin's Gmail script sends it.
        "email_configured": email_configured() or inbox is not None,
        "sends_from": None if email_configured() or inbox is None else inbox[0],
        "last_sent_at": user.last_digest_sent_at.isoformat() if user.last_digest_sent_at else None,
        "test_waiting": TEST_KEY in (user.preferences or {}),
    }
    if user.role == "admin":
        body["everyone"] = await everyone_gets_it(db)
    return body


@router.get("/settings")
async def get_notification_settings(user: CurrentUser, db: DbSession):
    return await _settings(db, user)


@router.put("/settings")
async def update_notification_settings(body: NotificationSettings, user: CurrentUser, db: DbSession):
    user = await db.get(User, user.id)  # this request's copy, so the change is saved
    if body.daily_email is not None:
        user.email_digest = body.daily_email
    if body.everyone is not None:
        if user.role != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can send it to everyone")
        user.preferences = {**(user.preferences or {}), EVERYONE_KEY: body.everyone}
    await db.commit()
    return await _settings(db, user)


async def _todays_email(db, user: User) -> tuple[bool, str, str, str]:
    return await todays_email(db, user)


@router.get("/digest/preview")
async def preview_digest(user: CurrentUser, db: DbSession):
    empty, subject, html, _ = await _todays_email(db, user)
    return {"empty": empty, "subject": subject, "html": html}


@router.post("/digest/test")
async def send_test_digest(user: CurrentUser, db: DbSession):
    """Sends even when there's nothing new, so the user sees what arrives.
    Doesn't count as the day's email. With the Gmail script sending, it's
    queued and goes out on the script's next run, within 10 minutes."""
    if not email_configured():
        from app.services.job_alerts.forwarding import shared_inbox

        if await shared_inbox(db) is None:
            raise HTTPException(status_code=503, detail="Email sending isn't set up yet")
        user = await db.get(User, user.id)  # this request's copy, so the change is saved
        user.preferences = {**(user.preferences or {}), TEST_KEY: datetime.now(timezone.utc).isoformat()}
        await db.commit()
        return {"sent_to": user.email, "queued": True}
    _, subject, html, text = await _todays_email(db, user)
    try:
        await send_email(to=user.email, subject=f"[Test] {subject}", html=html, text=text,
                         unsubscribe_url=unsubscribe_url(user.id))
    except EmailNotConfigured:
        raise HTTPException(status_code=503, detail="Email sending isn't set up yet")
    except EmailFailed as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"sent_to": user.email}


def _page(title: str, message: str) -> HTMLResponse:
    profile = f"{frontend_url()}/dashboard/profile"
    return HTMLResponse(
        '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{title}</title>"
        '<body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#f6f5f2;margin:0;padding:48px 16px;">'
        '<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;padding:28px 24px;">'
        f'<h1 style="font-size:20px;margin:0 0 8px;">{title}</h1><p style="color:#444;line-height:1.5;">{message}</p>'
        f'<p><a href="{profile}" style="color:#1f5fd1;">Email settings on your profile</a></p></div></body>'
    )


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(u: UUID, t: str, db: DbSession):
    user = await db.get(User, u)
    if user is None or not valid_unsubscribe_token(u, t):
        return _page("This link doesn't work", "Turn the daily email off on your profile instead.")
    user.email_digest = False
    await db.commit()
    return _page("You won't get daily emails", "You can turn them back on any time on your profile.")
