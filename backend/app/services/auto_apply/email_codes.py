"""Forms that email the applicant a code before they'll send.

Some companies' Greenhouse forms, once Submit is pressed, email a code
"to confirm you're a human" and only send after it's typed in. That's a
check that a person is applying, so the app never does that step: those
applications are sent from the user's own browser (the extension fills in
the form, the user types the code). The app learns a form does this the
first time a send meets the step (result["send"]["status"] == "email_code").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auto_apply import AutoApplication
from app.services.auto_apply.ats import detect_ats

STATUS = "email_code"
# Seen before the app could tell: Anthropic's form asked for a code on the
# first real send, 2026-10-04.
KNOWN_BOARDS = frozenset({("greenhouse", "anthropic")})


def board_of(url: str | None) -> tuple[str, str] | None:
    target = detect_ats(url)
    if target is None or not target.board:
        return None
    return target.ats, target.board.lower()


async def boards_asking_for_codes(db: AsyncSession) -> frozenset[tuple[str, str]]:
    """Every board known to email a code: the ones seen before, and any a
    send has met since, for any user."""
    urls = (await db.execute(
        select(AutoApplication.form_url).where(AutoApplication.result["send"]["status"].astext == STATUS)
    )).scalars().all()
    return KNOWN_BOARDS | {board for board in map(board_of, urls) if board}


def asks_for_code(application: AutoApplication, boards: frozenset[tuple[str, str]] = KNOWN_BOARDS) -> bool:
    if ((application.result or {}).get("send") or {}).get("status") == STATUS:
        return True
    return board_of(application.form_url) in boards


def message(company: str | None) -> str:
    who = f"{company}'s form" if company else "The company's form"
    return (
        f"{who} emails you a code to prove a person is applying, and the app doesn't do that step, "
        "so nothing was sent. Send this one from your own browser: the extension fills in the form, "
        "and you type in the code."
    )
