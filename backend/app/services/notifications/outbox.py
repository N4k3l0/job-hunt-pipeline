"""Emails the Gmail script sends.

The admin's LinkedIn alert script (frontend/src/lib/linkedin-alert-script.ts)
runs every 10 minutes in a Gmail account. Besides sending alert emails to
the app, it asks for emails to send (`due_emails`), sends them from that
Gmail, and says which went (`mark_sent`). So the daily email needs no
email service: no domain, no keys in Railway. Railway's plan blocks SMTP,
which is why sending happens there.

An email that went out but wasn't reported (the script stopped half way)
is sent again on the next run; that's rarer than losing one.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select

from app.models.user import User
from app.services.notifications.digest import TEST_KEY, recipients_due, todays_email

# A run sends at most this many; the next one carries on.
PER_RUN = 10


async def due_emails(db, *, now: datetime | None = None, limit: int = PER_RUN) -> list[dict]:
    """Test emails users asked for, then today's emails that are due. A
    day with nothing new is marked done without an email."""
    now = now or datetime.now(timezone.utc)
    emails: list[dict] = []

    testers = (await db.execute(select(User).where(User.preferences.has_key(TEST_KEY)))).scalars().all()
    for user in testers[:limit]:
        _, subject, html, text = await todays_email(db, user, now)
        emails.append({"id": f"test:{user.id}", "to": user.email, "subject": f"[Test] {subject}", "html": html, "text": text})

    for user in await recipients_due(db, now):
        if len(emails) >= limit:
            break
        empty, subject, html, text = await todays_email(db, user, now)
        if empty:
            user.last_digest_sent_at = now
            continue
        emails.append({"id": f"digest:{user.id}", "to": user.email, "subject": subject, "html": html, "text": text})
    await db.commit()
    return emails


async def mark_sent(db, ids: list[str], *, now: datetime | None = None) -> int:
    """The script sent these. Returns how many were known."""
    now = now or datetime.now(timezone.utc)
    done = 0
    for item in ids:
        kind, _, raw_id = item.partition(":")
        try:
            user = await db.get(User, UUID(raw_id))
        except ValueError:
            continue
        if user is None:
            continue
        if kind == "digest":
            user.last_digest_sent_at = now
            done += 1
        elif kind == "test":
            user.preferences = {k: v for k, v in (user.preferences or {}).items() if k != TEST_KEY}
            done += 1
    await db.commit()
    return done
