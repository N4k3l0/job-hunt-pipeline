"""The message a user sends a person after applying.

Written only when the user asks for it, from the application that was
sent: the job, their own background, and the contact the app found. It is
never sent by the app. LinkedIn doesn't allow that, and it shouldn't:
the user reads it, changes what they want, and sends it themselves.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.prompts.tailor_resume import OUTREACH_PROMPT, SYSTEM_PROMPT
from app.llm.style import plain_english
from app.models.auto_apply import AutoApplication
from app.models.job import Job, JobContact
from app.models.tailoring import TailoredApplication
from app.models.user import User
from app.services.auto_apply.prepare import load_applicant

logger = logging.getLogger(__name__)


class NotSentYet(RuntimeError):
    """A follow-up only makes sense once the application has gone."""


async def draft_follow_up(db: AsyncSession, application: AutoApplication, llm=None) -> dict:
    """Draft the message and keep it on the application."""
    if application.status != "submitted":
        raise NotSentYet("Send the application first, then write to someone about it.")
    if llm is None:
        from app.llm.client import llm_client as llm

    job = await db.get(Job, application.job_id)
    user = await db.get(User, application.user_id)
    contact = (await db.execute(
        select(JobContact).where(JobContact.job_id == application.job_id)
    )).scalar_one_or_none()
    tailored = (await db.execute(
        select(TailoredApplication)
        .where(TailoredApplication.user_id == application.user_id,
               TailoredApplication.job_id == application.job_id)
        .order_by(TailoredApplication.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    _facts, facts_text, _resume, _saved = await load_applicant(db, application.user_id)
    summary = (tailored.tailored_summary if tailored else None) or facts_text[:1500]
    prompt = OUTREACH_PROMPT.format(
        job_title=(job.title_en or job.title) if job else "",
        job_company=(job.company if job else "") or "",
        candidate_name=(user.name if user else "") or "",
        candidate_summary=summary,
        top_experience=facts_text[:2000],
        strongest_matches=", ".join((tailored.tailored_resume_json or {}).get("strongest_matches", []))
        if tailored and tailored.tailored_resume_json else "",
    )
    if contact and contact.name:
        prompt += f"\n\n## Who it's going to\n{contact.name}"
        if contact.title:
            prompt += f", {contact.title}"
        prompt += "\nOpen with their first name."

    drafted = await llm.generate(task_type="tailoring", system_prompt=SYSTEM_PROMPT, user_prompt=prompt, max_tokens=500)
    message = plain_english(drafted)
    application.follow_up = {"message": message, "drafted_at": datetime.now(timezone.utc).isoformat()}
    await db.commit()
    logger.info("Drafted a follow-up for application %s", application.id)
    return application.follow_up
