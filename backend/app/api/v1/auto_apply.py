"""Applications the app prepares for the user ("Apply for me").

Preparing reads the job's form and drafts answers, which can take up to
half a minute when some answers are drafted with Claude. Once the answers
are approved, the browser extension fills in the company's form in the
user's own browser, and the user presses Submit there.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, CurrentUserId, DbSession
from app.models.auto_apply import AutoApplication
from app.models.job import Job
from app.services.auto_apply import answers as rules
from app.services.auto_apply.extension import (
    application_files,
    fill_details,
    mark_sent,
    valid_sent_token,
)
from app.services.auto_apply.prepare import (
    AnswerError,
    cancel_application,
    prepare_application,
    update_answers,
    write_first_go,
)
from app.services.job_freshness import closed_note
from app.services.outreach.follow_up import NotSentYet, draft_follow_up
from app.llm.style import has_dashes, read_through, saved_read, writing_problems
from app.services.auto_apply.drafting import rewrite_plainly
from app.services.auto_apply.resume_pdf import tailored_for_job
from app.services.auto_apply.writing import (
    accept_document_wording, application_document_problems, first_document_problem, wants_cover_letter,
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
            "closed_note": closed_note(job),
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
    body["sending"] = sending_state(application)
    body["prepared_by"] = (application.result or {}).get("prepared_by") or "user"
    if detail:
        answers = application.answers or {}
        kinds = rules.kinds(application.form or [], rules.JobFacts(company=(job.company if job else "") or ""))
        body["fields"] = [
            {
                **item,
                "kind": kinds[item["key"]],
                "answer": answers.get(item["key"]),
                "needs_attention": rules.needs_attention(item, answers.get(item["key"])),
                # What to change so the answer reads plainly (llm/style.py).
                "writing_problems": rules.answer_writing_problems(item, answers.get(item["key"])),
                "wording_ok": rules.wording_accepted(answers.get(item["key"])),
            }
            for item in application.form or []
        ]
        body["result"] = application.result
        body["follow_up"] = application.follow_up
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


class AutoPrepareSettings(BaseModel):
    per_day: int


def _auto_prepare_settings(user) -> dict:
    from app.services.auto_apply import auto_prepare

    return {
        "per_day": auto_prepare.per_day(user),
        "choices": list(auto_prepare.PER_DAY_CHOICES),
        "min_score": auto_prepare.MIN_SCORE,
        "cost_each_usd": auto_prepare.COST_EACH_USD,
    }


# Declared before "/{application_id}" so "settings" isn't read as an id.
@router.get("/settings")
async def get_auto_prepare_settings(user: CurrentUser):
    """How many of the user's best matches the app prepares by itself each day."""
    return _auto_prepare_settings(user)


@router.put("/settings")
async def update_auto_prepare_settings(body: AutoPrepareSettings, user: CurrentUser, db: DbSession):
    from app.services.auto_apply import auto_prepare

    if body.per_day not in auto_prepare.PER_DAY_CHOICES:
        raise HTTPException(status_code=422, detail="Choose one of the numbers offered.")
    # A new dict, so the change to the JSON column is saved.
    user.preferences = {**(user.preferences or {}), auto_prepare.PREFERENCE_KEY: body.per_day}
    await db.commit()
    return _auto_prepare_settings(user)


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
async def prepare_for_job(
    job_id: UUID,
    user_id: CurrentUserId,
    db: DbSession,
    tailor: bool = Query(True, description="Also write a resume for this job"),
):
    """Prepare (or re-prepare) the application for a job: read the form,
    answer what the profile answers, and tailor the resume."""
    if await db.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    application = await prepare_application(db, user_id, job_id, tailor=tailor)
    return serialize(await _load(db, user_id, application.id), detail=True)


@router.get("/{application_id}/documents")
async def documents(application_id: UUID, user_id: CurrentUserId, db: DbSession):
    """The files this application will attach, for the user to look at."""
    application = await _load(db, user_id, application_id)
    files = await application_files(db, application)
    files["writing_problems"] = await application_document_problems(db, application)
    return files


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


class AnswerKey(BaseModel):
    key: str


def _written_answer(application: AutoApplication, key: str) -> tuple[dict, dict]:
    item = next((f for f in application.form or [] if f["key"] == key), None)
    entry = (application.answers or {}).get(key)
    if item is None or not entry or not isinstance(entry.get("value"), str):
        raise HTTPException(status_code=404, detail="That question has no written answer.")
    return item, entry


@router.post("/{application_id}/rewrite")
async def rewrite_answer(application_id: UUID, body: AnswerKey, user_id: CurrentUserId, db: DbSession):
    """A plainer version of one answer, for the user to use or not. Nothing
    is saved until they choose it."""
    application = await _load(db, user_id, application_id)
    item, entry = _written_answer(application, body.key)
    suggestion = await rewrite_plainly(item["label"], entry["value"])
    problems = writing_problems(suggestion)
    try:
        found = await read_through(suggestion, what=f"an answer to the question \"{item['label']}\"")
    except Exception:  # noqa: BLE001 — it's read again when the user saves it
        found = None
    if found is not None:
        problems += found
        # Kept, so using the suggestion doesn't read the same words again.
        answers = dict(application.answers or {})
        answers[body.key] = {**entry, "suggested_read": saved_read(suggestion, found)}
        application.answers = answers
        await db.commit()
    return {"suggestion": suggestion, "writing_problems": problems}


@router.post("/{application_id}/first-go")
async def first_go(application_id: UUID, body: AnswerKey, user_id: CurrentUserId, db: DbSession):
    """The app writes a first go at a question it left empty, from the
    user's profile and the job. It's saved as a draft for them to change."""
    application = await _load(db, user_id, application_id)
    try:
        await write_first_go(db, application, body.key)
    except AnswerError as e:
        raise _answer_error(e) from e
    return serialize(await _load(db, user_id, application_id), detail=True)


@router.post("/{application_id}/keep-wording")
async def keep_wording(application_id: UUID, body: AnswerKey, user_id: CurrentUserId, db: DbSession):
    """The user says an answer is fine as it is, despite what the writing
    check flagged. Long dashes still have to come out."""
    application = await _load(db, user_id, application_id)
    item, entry = _written_answer(application, body.key)
    if has_dashes(entry["value"]):
        raise HTTPException(status_code=422, detail="Take the long dashes out first. The rest can stay as it is.")
    answers = dict(application.answers or {})
    answers[body.key] = rules.accept_wording(entry)
    application.answers = answers
    await db.commit()
    return serialize(await _load(db, user_id, application_id), detail=True)


class DocumentName(BaseModel):
    document: str  # "resume" or "cover_letter"


@router.post("/{application_id}/keep-document-wording")
async def keep_document_wording(application_id: UUID, body: DocumentName, user_id: CurrentUserId, db: DbSession):
    """The user says a document is fine as it is, despite what the writing
    check flagged. Long dashes still have to come out."""
    application = await _load(db, user_id, application_id)
    tailored = await tailored_for_job(db, application.user_id, application.job_id)
    if tailored is None:
        raise HTTPException(status_code=404, detail="This application has no document written for the job.")
    try:
        accept_document_wording(tailored, body.document, with_cover_letter=wants_cover_letter(application))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    await db.commit()
    files = await application_files(db, application)
    files["writing_problems"] = await application_document_problems(db, application)
    return files


class SendRequest(BaseModel):
    practice: bool = False


def _outcome_view(outcome: dict | None) -> dict | None:
    if not outcome:
        return None
    return {
        "status": outcome.get("status"),
        "message": outcome.get("message"),
        "filled": outcome.get("filled"),
        "not_filled": [item.get("label") for item in outcome.get("not_filled") or []],
        "at": outcome.get("at"),
        "has_screenshot": bool(outcome.get("screenshot")),
    }


def sending_state(application: AutoApplication) -> dict:
    """Where "Send it for me" stands: waiting, running, and the last
    practice run and real send."""
    result = application.result or {}
    waiting = result.get("request") or result.get("running")
    return {
        "waiting": {"practice": bool(waiting.get("practice")), "since": waiting.get("at"),
                    "running": "running" in result} if waiting else None,
        "practice": _outcome_view(result.get("practice")),
        "send": _outcome_view(result.get("send")),
    }


@router.post("/{application_id}/send")
async def send_for_me(application_id: UUID, body: SendRequest, user_id: CurrentUserId, db: DbSession):
    """Ask the app's own browser to fill in the company's form and send it
    (or, with `practice`, fill it in without sending). The sender picks it
    up within about five minutes."""
    application = await _load(db, user_id, application_id)
    if application.status == "submitted":
        raise HTTPException(status_code=409, detail="This application has already been sent.")
    if application.status != "queued":
        raise HTTPException(status_code=409, detail="Approve the answers first.")
    result = application.result or {}
    if "request" in result or "running" in result:
        raise HTTPException(status_code=409, detail="It's already waiting to go.")
    # Everything it sends has to read plainly, now as when it was approved.
    answers = application.answers or {}
    flagged = [f["label"] for f in application.form or [] if rules.needs_attention(f, answers.get(f["key"]))]
    if flagged:
        raise HTTPException(status_code=409, detail=f"“{flagged[0]}” needs you before it can be sent.")
    document = first_document_problem(await application_document_problems(db, application, read=False))
    if document:
        raise HTTPException(status_code=409, detail=document)
    application.result = {**result, "request": {"practice": body.practice, "at": datetime.now(timezone.utc).isoformat()}}
    application.error = None
    await db.commit()
    return serialize(await _load(db, user_id, application_id), detail=True)


@router.get("/{application_id}/send-screenshot")
async def send_screenshot(application_id: UUID, user_id: CurrentUserId, db: DbSession, what: str = "practice"):
    """A short-lived link to the picture of the form as the app left it."""
    application = await _load(db, user_id, application_id)
    path = ((application.result or {}).get(what) or {}).get("screenshot")
    if what not in ("practice", "send") or not path:
        raise HTTPException(status_code=404, detail="There's no picture of that run.")
    from app.services.storage import signed_url
    return {"url": await signed_url("resumes", path)}


@router.get("/{application_id}/fill")
async def fill_in(application_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Everything the extension needs to fill in the company's form."""
    application = await _load(db, user_id, application_id)
    if application.status == "submitted":
        raise HTTPException(status_code=409, detail="This application has already been sent.")
    if application.status != "queued":
        raise HTTPException(status_code=409, detail="Approve the answers before filling in the form.")
    return await fill_details(db, application)


@router.post("/{application_id}/sent")
async def sent(application_id: UUID, user_id: CurrentUserId, db: DbSession):
    """The user says they sent the application themselves."""
    application = await _load(db, user_id, application_id)
    try:
        await mark_sent(db, application)
    except AnswerError as e:
        raise _answer_error(e) from e
    return serialize(await _load(db, user_id, application_id), detail=False)


class ExtensionReport(BaseModel):
    token: str


@router.post("/{application_id}/sent-by-extension")
async def sent_by_extension(application_id: UUID, body: ExtensionReport, db: DbSession):
    """The extension saw the company's form accept the application. No
    login: the token from the fill-in only allows this."""
    if not valid_sent_token(application_id, body.token):
        raise HTTPException(status_code=403, detail="This link doesn't work")
    application = await db.get(AutoApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    try:
        await mark_sent(db, application)
    except AnswerError as e:
        raise _answer_error(e) from e
    return {"status": application.status}


@router.post("/{application_id}/follow-up")
async def follow_up(application_id: UUID, user_id: CurrentUserId, db: DbSession):
    """Draft a message to a person about this application. The app never
    sends it: the user copies it into LinkedIn or their email."""
    application = await _load(db, user_id, application_id)
    try:
        return await draft_follow_up(db, application)
    except NotSentYet as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/{application_id}/cancel")
async def cancel(application_id: UUID, user_id: CurrentUserId, db: DbSession):
    application = await _load(db, user_id, application_id)
    try:
        await cancel_application(db, application)
    except AnswerError as e:
        raise _answer_error(e) from e
    return serialize(await _load(db, user_id, application_id), detail=False)
