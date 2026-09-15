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
    build_digest, digest_window_start, render_digest, unsubscribe_url, valid_unsubscribe_token,
)
from app.services.notifications.email import (
    EmailFailed, EmailNotConfigured, email_configured, frontend_url, send_email,
)

router = APIRouter()


class NotificationSettings(BaseModel):
    daily_email: bool


def _settings(user: User) -> dict:
    return {
        "daily_email": user.email_digest,
        "email": user.email,
        "email_configured": email_configured(),
        "last_sent_at": user.last_digest_sent_at.isoformat() if user.last_digest_sent_at else None,
    }


@router.get("/settings")
async def get_notification_settings(user: CurrentUser):
    return _settings(user)


@router.put("/settings")
async def update_notification_settings(body: NotificationSettings, user: CurrentUser, db: DbSession):
    user.email_digest = body.daily_email
    await db.commit()
    return _settings(user)


async def _todays_email(db, user: User) -> tuple[bool, str, str, str]:
    digest = await build_digest(db, user, since=digest_window_start(user, datetime.now(timezone.utc)))
    subject, html, text = render_digest(digest, unsubscribe=unsubscribe_url(user.id))
    return digest.is_empty, subject, html, text


@router.get("/digest/preview")
async def preview_digest(user: CurrentUser, db: DbSession):
    empty, subject, html, _ = await _todays_email(db, user)
    return {"empty": empty, "subject": subject, "html": html}


@router.post("/digest/test")
async def send_test_digest(user: CurrentUser, db: DbSession):
    """Sends even when there's nothing new, so the user sees what arrives.
    Doesn't count as the day's email."""
    if not email_configured():
        raise HTTPException(status_code=503, detail="Email sending isn't set up yet")
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
        f'<p><a href="{profile}" style="color:#1f9d7a;">Email settings on your profile</a></p></div></body>'
    )


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(u: UUID, t: str, db: DbSession):
    user = await db.get(User, u)
    if user is None or not valid_unsubscribe_token(u, t):
        return _page("This link doesn't work", "Turn the daily email off on your profile instead.")
    user.email_digest = False
    await db.commit()
    return _page("You won't get daily emails", "You can turn them back on any time on your profile.")
