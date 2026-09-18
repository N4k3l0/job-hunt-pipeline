"""What the browser extension needs to fill in an application form, and
recording that the user sent it.

The extension has no login of its own. The app page, where the user is
signed in, asks for the fill-in and hands it to the extension. It carries a
token that lets the extension report one thing: that this application was
sent.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.auto_apply import AutoApplication
from app.models.candidate import Resume
from app.models.job import Job
from app.models.user import User
from app.services.auto_apply import answers as rules
from app.services.auto_apply.prepare import AnswerError
from app.services.auto_apply.resume_pdf import (
    build_letter_pdf,
    build_resume_pdf,
    resume_data,
    tailored_for_job,
)
from app.services.notifications.email import api_public_url
from app.services.storage import object_path, signed_url, upload_file
from app.services.tracking.applied import record_applied

logger = logging.getLogger(__name__)

SENDABLE_STATUSES = ("needs_you", "queued", "submitting")
_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def sent_token(application_id: UUID) -> str:
    key = (get_settings().supabase_jwt_secret or "").encode()
    return hmac.new(key, f"auto-apply-sent:{application_id}".encode(), hashlib.sha256).hexdigest()[:40]


def valid_sent_token(application_id: UUID, token: str) -> bool:
    return bool(get_settings().supabase_jwt_secret) and hmac.compare_digest(sent_token(application_id), token or "")


def _file_name(user: User | None, what: str, extension: str = "pdf") -> str:
    name = ((user.name if user else "") or "").strip().replace("/", "-")
    return f"{name + ' ' if name else ''}{what}.{extension}"


async def _store_pdf(application: AutoApplication, what: str, content: bytes, filename: str) -> dict | None:
    """Put a generated file where the browser filling in the form can read
    it: a path of its own, replaced each time it's built."""
    path = f"applications/{application.user_id}/{application.id}-{what}.pdf"
    try:
        await upload_file("resumes", path, content, "application/pdf")
        return {"url": await signed_url("resumes", path), "filename": filename, "content_type": "application/pdf"}
    except Exception as e:  # noqa: BLE001 — the user can attach it on the form themselves
        logger.warning("Couldn't store the %s for application %s: %s", what, application.id, e)
        return None


async def _stored_resume(db: AsyncSession, application: AutoApplication, user: User | None) -> dict | None:
    """The file the user uploaded to their profile."""
    resume = await db.get(Resume, application.resume_id) if application.resume_id else None
    if resume is None or resume.user_id != application.user_id:
        return None
    path = object_path("resumes", resume.file_url)
    extension = (resume.source_type or path.rsplit(".", 1)[-1] or "pdf").lower()
    try:
        url = await signed_url("resumes", path)
    except Exception as e:  # noqa: BLE001 — the user can attach it on the form themselves
        logger.warning("Couldn't sign resume link for application %s: %s", application.id, e)
        return None
    return {
        "url": url,
        "filename": _file_name(user, "Resume", extension),
        "content_type": _CONTENT_TYPES.get(extension, "application/octet-stream"),
    }


async def _resume_file(db: AsyncSession, application: AutoApplication, user: User | None) -> dict | None:
    """The resume tailored for this job when there is one, else the
    profile's file."""
    tailored = await tailored_for_job(db, application.user_id, application.job_id)
    if tailored is None or not tailored.tailored_resume_json:
        return await _stored_resume(db, application, user)
    data = await resume_data(db, application.user_id, tailored)
    stored = await _store_pdf(application, "resume", build_resume_pdf(data), _file_name(user, "Resume"))
    return stored or await _stored_resume(db, application, user)


async def _cover_letter_file(db: AsyncSession, application: AutoApplication, user: User | None) -> dict | None:
    """Only written when the form asks for one."""
    tailored = await tailored_for_job(db, application.user_id, application.job_id)
    if tailored is None or not (tailored.cover_letter or "").strip():
        return None
    data = await resume_data(db, application.user_id, tailored)
    return await _store_pdf(
        application, "cover-letter", build_letter_pdf(data, tailored.cover_letter),
        _file_name(user, "Cover Letter"),
    )


async def application_files(db: AsyncSession, application: AutoApplication) -> dict:
    """The resume and cover letter this application attaches, and whether
    they were written for this job."""
    user = await db.get(User, application.user_id)
    tailored = await tailored_for_job(db, application.user_id, application.job_id)
    wants_letter = any(rules.kinds(application.form or [], rules.JobFacts(company="")).get(item["key"]) == "cover_letter"
                       for item in application.form or [])
    return {
        "resume": await _resume_file(db, application, user),
        "cover_letter": await _cover_letter_file(db, application, user) if wants_letter else None,
        "tailored": tailored is not None and bool(tailored.tailored_resume_json),
        "tailored_id": str(tailored.id) if tailored else None,
    }


async def fill_details(db: AsyncSession, application: AutoApplication) -> dict:
    """The form's questions with the approved answers, the resume to
    attach, and where the extension reports that the form was sent."""
    job = await db.get(Job, application.job_id)
    user = await db.get(User, application.user_id)
    answers = application.answers or {}
    form = application.form or []
    kinds = rules.kinds(form, rules.JobFacts(company=(job.company if job else "") or ""))
    fields = [
        {
            "key": item["key"],
            "label": item["label"],
            "type": item["type"],
            "kind": kinds[item["key"]],
            "required": item["required"],
            "group": item.get("group") or "application",
            "options": item.get("options"),
            "value": (answers.get(item["key"]) or {}).get("value"),
        }
        for item in form
    ]
    wants_resume = any(f["kind"] == "resume" and not rules.is_empty(f["value"]) for f in fields)
    wants_letter = any(f["kind"] == "cover_letter" for f in fields)
    base = api_public_url()
    return {
        "application_id": str(application.id),
        "ats": application.ats,
        "form_url": application.form_url,
        "job": {"title": (job.title_en or job.title) if job else None, "company": job.company if job else None},
        "fields": fields,
        "resume": await _resume_file(db, application, user) if wants_resume else None,
        "cover_letter": await _cover_letter_file(db, application, user) if wants_letter else None,
        "sent_url": f"{base}/api/v1/auto-apply/{application.id}/sent-by-extension" if base else None,
        "sent_token": sent_token(application.id),
    }


async def mark_sent(db: AsyncSession, application: AutoApplication) -> AutoApplication:
    """The user sent the application: record it and track the job as applied."""
    if application.status == "submitted":
        return application
    if application.status not in SENDABLE_STATUSES:
        raise AnswerError("This application was stopped or couldn't be prepared.")
    application.status = "submitted"
    application.submitted_at = datetime.now(timezone.utc)
    application.error = None
    await record_applied(db, application.user_id, application.job_id)
    await db.commit()
    return application
