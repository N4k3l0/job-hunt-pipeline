from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.tailoring import TailoredApplication
from app.models.job import Job
from app.schemas.job import TailoredApplicationResponse, TailoredApplicationUpdate

router = APIRouter()


@router.post("/generate/{job_id}")
async def generate_tailored_materials(
    job_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Run the tailoring pipeline synchronously inside the request. We create
    a placeholder row first so the Review page (polling on a different request)
    can render a live "generating" card while this function does its 30-60s
    of LLM work, then refresh once we mark it ready.

    PDF generation is intentionally skipped — frontend renders a print-friendly
    HTML view instead (Vercel can't ship the WeasyPrint system libs)."""
    job_result = await db.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.job_id == job_id,
            TailoredApplication.user_id == user_id,
            TailoredApplication.approval_status.in_(["pending", "generating"]),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Tailoring already in progress for this job")

    placeholder = TailoredApplication(
        job_id=job_id,
        user_id=user_id,
        approval_status="generating",
        progress_step="Queued",
    )
    db.add(placeholder)
    await db.commit()
    await db.refresh(placeholder)

    # Update progress in-line between LLM steps so the Review page's polling
    # can show the live timeline. Each commit is small — sub-millisecond.
    async def report(step: str) -> None:
        placeholder.progress_step = step
        await db.commit()

    try:
        await report("Fetching job description")
        from app.services.discovery.firecrawl_service import scrape_url
        import asyncio
        if (not job.raw_description or len(job.raw_description) < 500) and job.job_url:
            try:
                # Hard cap on the enrichment scrape — Firecrawl's own
                # client timeout is 60s but Vercel will SIGKILL the whole
                # function at 60s, and we still need budget for 3 LLM
                # calls after this. 20s lets us bail and tailor with the
                # short description we already have instead of crashing.
                full = await asyncio.wait_for(scrape_url(job.job_url), timeout=20.0)
                if full and len(full) > len(job.raw_description or ""):
                    job.raw_description = full
                    await db.flush()
            except (Exception, asyncio.TimeoutError) as enrich_err:
                # Non-fatal — tailor with what we have.
                import logging
                logging.getLogger(__name__).warning("Description enrich failed: %s", enrich_err)

        from app.services.tailoring.tailor_service import generate_tailored_application as tailor
        application = await tailor(
            db, str(job_id), str(user_id),
            tailored_id=str(placeholder.id),
            progress_callback=report,
        )
        application.progress_step = None
        await db.commit()
    except Exception as e:
        # Mark as failed so the UI can show a retry button rather than spinning.
        placeholder.approval_status = "failed"
        placeholder.progress_step = str(e)[:500]
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Tailoring failed: {e}") from e

    return {
        "status": "complete",
        "job_id": str(job_id),
        "tailored_id": str(placeholder.id),
    }


@router.get("/queue")
async def get_review_queue(user_id: CurrentUserId, db: DbSession):
    """Get all tailored applications pending review, with job details. Includes
    `generating` (in-flight) and `failed` so the UI can render live status."""
    result = await db.execute(
        select(TailoredApplication)
        .where(
            TailoredApplication.user_id == user_id,
            TailoredApplication.approval_status.in_(["ready", "generating", "failed"]),
        )
        .options(selectinload(TailoredApplication.job))
        .order_by(TailoredApplication.created_at.desc())
    )
    apps = result.scalars().all()

    return [
        {
            "id": str(a.id),
            "job_id": str(a.job_id),
            "tailored_summary": a.tailored_summary,
            "cover_letter": a.cover_letter,
            "recruiter_message": a.recruiter_message,
            "short_answers": a.short_answers,
            "keyword_matches": a.keyword_matches,
            "validation_notes": a.validation_notes,
            "approval_status": a.approval_status,
            "progress_step": a.progress_step,
            "tailored_resume_url": a.tailored_resume_url,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            "job": {
                "title": a.job.title,
                "company": a.job.company,
                "location": a.job.location,
                "country": a.job.country,
                "remote_type": a.job.remote_type,
                "job_url": a.job.job_url,
                "apply_url": a.job.apply_url,
                "salary_text": a.job.salary_text,
            } if a.job else None,
        }
        for a in apps
    ]


@router.get("/{tailored_id}", response_model=TailoredApplicationResponse)
async def get_tailored_application(
    tailored_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Get a tailored application's full details."""
    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")
    return app


@router.put("/{tailored_id}", response_model=TailoredApplicationResponse)
async def update_tailored_application(
    tailored_id: UUID,
    data: TailoredApplicationUpdate,
    user_id: CurrentUserId,
    db: DbSession,
):
    """Edit tailored content before approval."""
    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")

    if app.approval_status == "approved":
        raise HTTPException(status_code=400, detail="Cannot edit approved applications")

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(app, field, value)

    await db.commit()
    await db.refresh(app)
    return app


@router.post("/{tailored_id}/approve")
async def approve_application(
    tailored_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Approve and lock a tailored application pack. Returns the tracking_id so the
    client can chain a follow-up status update (e.g. one-button apply)."""
    from datetime import datetime, timezone

    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")

    if app.approval_status == "approved":
        raise HTTPException(status_code=400, detail="Already approved")

    app.approval_status = "approved"
    app.approved_at = datetime.now(timezone.utc)

    from app.models.tracking import ApplicationTracking
    # Reuse the user's existing tracking row (e.g. they pressed "I applied"
    # before approving) so a job never ends up with two rows per user.
    tracking = (await db.execute(
        select(ApplicationTracking).where(
            ApplicationTracking.job_id == app.job_id,
            ApplicationTracking.user_id == user_id,
        ).order_by(ApplicationTracking.updated_at.desc()).limit(1)
    )).scalar_one_or_none()
    if tracking is None:
        tracking = ApplicationTracking(
            job_id=app.job_id,
            user_id=user_id,
            tailored_application_id=app.id,
            status="approved",
        )
        db.add(tracking)
    else:
        tracking.tailored_application_id = app.id

    await db.commit()
    await db.refresh(app)
    await db.refresh(tracking)

    return {
        "id": str(app.id),
        "job_id": str(app.job_id),
        "approval_status": app.approval_status,
        "approved_at": app.approved_at.isoformat() if app.approved_at else None,
        "tracking_id": str(tracking.id),
    }


@router.delete("/{tailored_id}")
async def delete_tailored_application(
    tailored_id: UUID, user_id: CurrentUserId, db: DbSession
):
    """Delete a tailored application from the review queue."""
    result = await db.execute(
        select(TailoredApplication).where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")

    await db.delete(app)
    await db.commit()
    return {"status": "deleted", "id": str(tailored_id)}


class RegenerateSection(BaseModel):
    section: str  # "tailored_summary" | "cover_letter" | "recruiter_message"
    guidance: str | None = None


@router.post("/{tailored_id}/regenerate-section")
async def regenerate_section(
    tailored_id: UUID,
    body: RegenerateSection,
    user_id: CurrentUserId,
    db: DbSession,
):
    """Regenerate a single section (summary / cover / outreach) with optional
    user guidance like 'lean harder on AI experience'. The section is rewritten
    in-place; we return the new content so the UI can update without polling."""
    if body.section not in ("tailored_summary", "cover_letter", "recruiter_message"):
        raise HTTPException(status_code=400, detail="Unknown section")

    result = await db.execute(
        select(TailoredApplication)
        .where(
            TailoredApplication.id == tailored_id,
            TailoredApplication.user_id == user_id,
        )
        .options(selectinload(TailoredApplication.job).selectinload(Job.entities))
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Tailored application not found")
    if app.approval_status == "approved":
        raise HTTPException(status_code=400, detail="Cannot edit approved applications")
    if app.approval_status == "generating":
        raise HTTPException(status_code=409, detail="Wait for tailoring to finish before regenerating")
    if not app.job:
        raise HTTPException(status_code=404, detail="Source job not found")

    from app.models.candidate import CandidateProfile
    from app.llm.client import llm_client
    from app.llm.prompts.tailor_resume import (
        SYSTEM_PROMPT, COVER_LETTER_PROMPT, OUTREACH_PROMPT, SUMMARY_REGEN_PROMPT,
    )
    from app.services.tailoring.tailor_service import (
        _load_samples_by_kind, _style_examples_block, _strip_llm_fluff,
    )

    profile_result = await db.execute(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user_id)
        .options(
            selectinload(CandidateProfile.work_history),
        )
    )
    profile = profile_result.scalar_one_or_none()
    samples_by_kind = await _load_samples_by_kind(db, str(user_id))
    # Map regenerate-section names to sample kinds.
    _section_to_kind = {
        "tailored_summary": "summary",
        "cover_letter": "cover_letter",
        "recruiter_message": "outreach",
    }
    _section_to_label = {
        "tailored_summary": "summary",
        "cover_letter": "cover letter",
        "recruiter_message": "outreach message",
    }
    style_block = _style_examples_block(
        samples_by_kind.get(_section_to_kind.get(body.section, ""), []),
        _section_to_label.get(body.section, "draft"),
    )

    job = app.job
    requirements = job.entities.requirements if job.entities else []
    skills = job.entities.skills if job.entities else []
    guidance_block = (
        f"## Additional guidance from the user\n{body.guidance.strip()}\n"
        if body.guidance and body.guidance.strip()
        else ""
    )
    # Current models don't accept `temperature`, which used to make
    # re-rolls differ; ask for variety in the prompt instead.
    guidance_block += (
        "This replaces a draft the candidate asked to redo, so vary the "
        "phrasing and structure rather than playing it safe.\n"
    )

    # Build "top experience" string from the existing tailored resume so the
    # regenerated section stays consistent with what the user already has.
    top_exp_lines = []
    if app.tailored_resume_json:
        for e in (app.tailored_resume_json.get("selected_experience") or [])[:3]:
            bullets = "; ".join((e.get("bullets") or [])[:2])
            top_exp_lines.append(f"- {e.get('company', '')}: {bullets}")
    top_exp = "\n".join(top_exp_lines) or "(no prior tailored bullets — use the candidate's master profile)"

    if body.section == "tailored_summary":
        prompt = style_block + SUMMARY_REGEN_PROMPT.format(
            job_title=job.title,
            job_company=job.company,
            job_requirements="; ".join(requirements[:15]),
            job_skills=", ".join(skills[:20]),
            candidate_headline=(profile.headline if profile else ""),
            candidate_summary=(profile.master_summary if profile else ""),
            top_experience=top_exp,
            guidance_block=guidance_block,
        )
        new_content = (await llm_client.generate(
            task_type="tailoring",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            max_tokens=400,
        )).strip()
        app.tailored_summary = new_content
    elif body.section == "cover_letter":
        # Authoritative name from the User row — never let the model
        # invent a name from resume context.
        from app.models.user import User
        user_row = (await db.execute(
            select(User.name).where(User.id == user_id)
        )).first()
        candidate_name = (user_row[0] if user_row else None) or "the candidate"
        base = COVER_LETTER_PROMPT.format(
            job_title=job.title,
            job_company=job.company,
            job_requirements="; ".join(requirements[:10]),
            candidate_name=candidate_name,
            candidate_summary=app.tailored_summary or (profile.master_summary if profile else ""),
            top_experience=top_exp,
        )
        prompt = style_block + base + ("\n\n" + guidance_block if guidance_block else "")
        new_content = _strip_llm_fluff(await llm_client.generate(
            task_type="tailoring",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            max_tokens=1200,
        ))
        app.cover_letter = new_content
    else:  # recruiter_message
        # OUTREACH_PROMPT now requires candidate_name + candidate_summary +
        # top_experience (not just strongest_matches) so the model has
        # real material to work from instead of asking for more info.
        from app.models.user import User
        user_row = (await db.execute(
            select(User.name).where(User.id == user_id)
        )).first()
        candidate_name = (user_row[0] if user_row else None) or "the candidate"
        strongest = (app.validation_notes or {}).get("strongest_matches", [])
        base = OUTREACH_PROMPT.format(
            job_title=job.title,
            job_company=job.company,
            candidate_name=candidate_name,
            candidate_summary=(
                app.tailored_summary
                or (profile.master_summary if profile else "")
                or (profile.headline if profile else "")
                or ""
            ),
            top_experience=top_exp,
            strongest_matches="; ".join(strongest),
        )
        prompt = style_block + base + ("\n\n" + guidance_block if guidance_block else "")
        new_content = _strip_llm_fluff(await llm_client.generate(
            task_type="tailoring",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            max_tokens=500,
        ))
        app.recruiter_message = new_content

    await db.commit()
    return {"section": body.section, "content": new_content}

