"""One shared Gmail inbox for everyone's LinkedIn job alerts.

An admin runs the alert script (frontend/src/lib/linkedin-alert-script.ts)
once, in the Gmail account that gets their own LinkedIn alerts. Every other
user forwards their alerts there with a Gmail filter, to a personal
address: the inbox's address with their code after a plus,
`inbox+k7f3q2xa@gmail.com`. Gmail delivers plus addresses to the inbox and
records which one it was delivered to, so the script sends those headers
and the backend finds whose alerts they are. The admin's own alerts have no
code and stay the admin's.

Gmail asks for proof before it forwards anywhere: it emails a confirmation
code to the new address. The script sends those emails too, and the code
is shown to the user it's for, to type into Gmail.

Moving to a different inbox later: have the old account forward everything
to the new one, then run the script there. Users change nothing.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

CODE_KEY = "alert_forward_code"
CONFIRMATION_KEY = "alert_forward_confirmation"
INBOX_KEY = "alert_inbox"
GMAIL_FORWARDING_SENDER = "forwarding-noreply@google.com"

_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (0/o, 1/l/i)
_CODE_LENGTH = 8
_PLUS_TAG = re.compile(r"\+([a-z0-9]{6,16})@", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def personal_address(inbox: str, code: str) -> str:
    local, _, domain = inbox.strip().lower().partition("@")
    return f"{local.split('+')[0]}+{code}@{domain}"


def codes_in(recipients: list[str]) -> list[str]:
    """The plus codes in the addresses an email was delivered to."""
    found = []
    for value in recipients or []:
        for code in _PLUS_TAG.findall(value or ""):
            if code.lower() not in found:
                found.append(code.lower())
    return found


def read_confirmation(subject: str | None, text: str | None) -> dict | None:
    """Gmail's forwarding confirmation: the code to type into Gmail, and
    the address that asked to forward. None if it isn't one."""
    subject, text = subject or "", text or ""
    code = re.search(r"\(#(\d{6,12})\)", subject) or re.search(r"(?:confirmation )?code:?\s*(\d{6,12})", text, re.I)
    if not code:
        return None
    requester = (
        re.search(r"receive mail from\s+(" + _EMAIL.pattern + ")", subject, re.I)
        or re.search("(" + _EMAIL.pattern + r")\s+has requested", text, re.I)
    )
    return {"code": code.group(1), "from": requester.group(1).lower() if requester else None}


async def ensure_code(db: AsyncSession, user: User) -> str:
    """The user's code, made the first time it's asked for."""
    code = (user.preferences or {}).get(CODE_KEY)
    if code:
        return code
    while True:
        code = new_code()
        if await user_with_code(db, code) is None:
            break
    user.preferences = {**(user.preferences or {}), CODE_KEY: code}
    await db.commit()
    return code


async def user_with_code(db: AsyncSession, code: str) -> User | None:
    return (await db.execute(
        select(User).where(User.preferences[CODE_KEY].astext == code.lower())
    )).scalars().first()


async def shared_inbox(db: AsyncSession) -> tuple[str, User] | None:
    """The shared inbox's address and the admin whose script reads it."""
    admin = (await db.execute(
        select(User).where(User.role == "admin", User.preferences[INBOX_KEY].astext.is_not(None))
        .order_by(User.created_at)
    )).scalars().first()
    if admin is None:
        return None
    return admin.preferences[INBOX_KEY], admin


def remember_inbox(owner: User, address: str | None) -> None:
    """An admin's script reports the inbox it reads."""
    if not address or owner.role != "admin" or not _EMAIL.fullmatch(address.strip()):
        return
    address = address.strip().lower()
    if (owner.preferences or {}).get(INBOX_KEY) != address:
        owner.preferences = {**(owner.preferences or {}), INBOX_KEY: address}


def remember_confirmation(user: User, confirmation: dict) -> None:
    user.preferences = {
        **(user.preferences or {}),
        CONFIRMATION_KEY: {**confirmation, "at": datetime.now(timezone.utc).isoformat()},
    }
