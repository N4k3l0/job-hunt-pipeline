"""Applications the app prepares for the user ("Apply for me").

Preparing reads the job's form and drafts answers, which can take up to
half a minute when some answers are drafted with Claude.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.auto_apply import AutoApplication
from app.models.job import Job
from app.services.auto_apply import answers as rules
from app.services.auto_apply.prepare import (
    AnswerError,
    cancel_application,
    prepare_application,
    update_answers,
)

router = APIRouter()


class AnswersUpdate(BaseModel):
    answers: dict = {}
    approve: bool = False


def _open_count(application: AutoApplication) -> int:
    answers = application.answers or {}
    return sum(1 for f in application.form or [] if rules.needs_attention(f, answers.get(f["key"])))


def serialize(application: AutoApplication, *, detail: bool) -> dict:
    job = application.job
    body = {
        "id": str(application.id),
        "job_id": str(application.job_id),
        "job": {
            "id": str(job.id),
            "title": job.title_en or job.title,
            "company": job.company,
            "location": job.location,
        } if job else None,
        "status": application.status,
        "ats": application.ats,
        "form_url": application.form_url,
        "open_count": _open_count(application),
        "error": application.error,
        "submitted_at": application.submitted_at.isoformat() if application.submitted_at else None,
        "created_at": application.created_at.isoformat() if application.created_at else None,
        "updated_at": application.updated_at.isoformat() if application.updated_at else None,
    }
    if detail:
        answers = application.answers or {}
        kinds = rules.kinds(application.form or [], rules.JobFacts(company=(job.company if job else "") or ""))
        body["fields"] = [
            {
                **item,
                "kind": kinds[item["key"]],
                "answer": answers.get(item["key"]),
                "needs_attention": rules.needs_attention(item, answers.get(item["key"])),
            }
            for item in application.form or []
        ]
        body["result"] = application.result
    return body


async def _load(db, user_id, application_id: UUID) -> AutoApplication:
    application = (await db.execute(
        select(AutoApplication)
        .where(AutoApplication.id == application_id, AutoApplication.user_id == user_id)
        .options(selectinload(AutoApplication.job))
    )).scalar_one_or_none()
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def _answer_error(e: AnswerError) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": str(e), "fields": e.fields})


@router.get("")
async def list_applications(user_id: CurrentUserId, db: DbSession, job_id: UUID | None = Query(None)):
    query = (
        select(AutoApplication)
        .where(AutoApplication.user_id == user_id)
        .options(selectinload(AutoApplication.job))
        .order_by(AutoApplication.updated_at.desc())
    )
    if job_id is not None:
        query = query.where(AutoApplication.job_id == job_id)
    applications = (await db.execute(query)).scalars().all()
    return [serialize(a, detail=False) for a in applications]


@router.post("/jobs/{job_id}")
async def prepare_for_job(job_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Prepare (or re-prepare) the application for a job."""
    if await db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    application = await prepare_application(db, user_id, job_id)
    return serialize(await _load(db, user_id, application.id), detail=True)


@router.get("/{application_id}")
async def get_application(application_id: UUID, user_id: CurrentUserId, db: DbSession):
    return serialize(await _load(db, user_id, application_id), detail=True)


@router.put("/{application_id}/answers")
async def save_answers(application_id: UUID, body: AnswersUpdate, user_id: CurrentUserId, db: DbSession):
    """Save the user's answers. `approve` also queues the application to
    send, which needs every question answered and confirmed."""
    application = await _load(db, user_id, application_id)
    try:
        await update_answers(db, application, body.answers, approve=body.approve)
    except AnswerError as e:
        raise _answer_error(e) from e
    return serialize(await _load(db, user_id, application_id), detail=True)


@router.post("/{application_id}/cancel")
async def cancel(application_id: UUID, user_id: CurrentUserId, db: DbSession):
    application = await _load(db, user_id, application_id)
    try:
        await cancel_application(db, application)
    except AnswerError as e:
        raise _answer_error(e) from e
    return serialize(await _load(db, user_id, application_id), detail=False)
