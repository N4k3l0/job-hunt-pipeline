from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from pydantic import BaseModel, Field

from app.models.candidate import (
    CandidateProfile,
    CandidateWorkHistory,
    CandidateSkill,
    CandidateEducation,
    CandidateBullet,
    Resume,
    SampleApplication,
)
from app.schemas.candidate import (
    ProfileCreate,
    ProfileUpdate,
    ProfileResponse,
    WorkHistoryCreate,
    WorkHistoryResponse,
    SkillCreate,
    SkillResponse,
    BulletCreate,
    BulletResponse,
    ResumeResponse,
)

router = APIRouter()


# ── Profile ──────────────────────────────────────────────────────────────────


@router.get("/profile", response_model=ProfileResponse | None)
async def get_profile(user_id: CurrentUserId, db: DbSession):
    result = await db.execute(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user_id)
        .options(
            selectinload(CandidateProfile.work_history),
            selectinload(CandidateProfile.skills),
            selectinload(CandidateProfile.education),
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return None
    return profile


@router.post("/profile", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_profile(data: ProfileCreate, user_id: CurrentUserId, db: DbSession):
    existing = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Profile already exists. Use PUT to update.")

    profile = CandidateProfile(user_id=user_id, **data.model_dump(exclude_none=True))
    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    # Score the newest 300 unscored jobs synchronously so a user who
    # creates a profile (but hasn't uploaded a resume yet) still lands
    # in a populated inbox. Pure deterministic compute, runs in seconds.
    from app.workers.scoring_tasks import _batch_score_async
    try:
        await _batch_score_async(str(user_id), rescore_all=False)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("Initial scoring after profile create failed: %s", e)

    return profile


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(data: ProfileUpdate, user_id: CurrentUserId, db: DbSession):
    result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    update_data = data.model_dump(exclude_none=True)

    # Detect target_roles changes — if the user's intent shifted (e.g. PM
    # → AI Engineer), every existing score is stale because the scorer
    # gates which path runs by target_roles. We wipe-and-rescore in that
    # case so the inbox reflects the new intent immediately.
    old_roles = sorted(profile.target_roles or [])
    new_roles = sorted(update_data.get("target_roles", profile.target_roles) or [])
    roles_changed = "target_roles" in update_data and old_roles != new_roles

    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)

    if roles_changed:
        from app.workers.scoring_tasks import _batch_score_async
        try:
            await _batch_score_async(str(user_id), rescore_all=True)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).error("Rescore after target_roles change failed: %s", e)

    return profile


# ── Work History ─────────────────────────────────────────────────────────────


@router.post("/auto-suggest-roles")
async def auto_suggest_roles(user_id: CurrentUserId, db: DbSession):
    """One-shot heal for users whose target_roles is empty.

    Older users (parsed before commit 0833c1e shipped the auto-suggest
    in the resume parser) are stuck with target_roles=null forever
    because the resume parse is idempotent. Without target_roles the
    scorer falls back to running BOTH paths and inflates AI Engineer
    titles via tech-adjacent skills.

    If they already have target_roles set, this is a no-op. If they
    don't have any parsed resume content yet, we can't infer anything
    — return suggested:[] and let them fill it manually.

    Otherwise: ask Claude to read their work_history + skills and
    suggest 2-3 target roles, save them, and rescore the whole inbox
    so the change takes effect immediately.
    """
    from app.models.candidate import CandidateProfile, CandidateWorkHistory, CandidateSkill
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(CandidateProfile)
        .where(CandidateProfile.user_id == user_id)
        .options(
            selectinload(CandidateProfile.work_history),
            selectinload(CandidateProfile.skills),
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {"suggested": [], "applied": False, "reason": "no_profile"}

    # Already set — don't clobber.
    if profile.target_roles and len(profile.target_roles) > 0:
        return {"suggested": profile.target_roles, "applied": False, "reason": "already_set"}

    # Need parsed resume content to infer anything sensible.
    if not profile.work_history:
        return {"suggested": [], "applied": False, "reason": "no_work_history"}

    # Build a compact summary for Claude — recent titles + companies + headline + skills.
    sorted_history = sorted(
        profile.work_history,
        key=lambda w: (w.start_date or w.end_date) or __import__("datetime").date.min,
        reverse=True,
    )
    recent_titles = [
        f"{w.title} @ {w.company}"
        for w in sorted_history[:5]
        if w.title and w.company
    ]
    skills = [
        s.skill_name for s in profile.skills
        if s.skill_name and s.category in ("technical", "tool", "domain")
    ][:30]

    from app.llm.client import llm_client
    prompt = (
        "Pick 2-3 canonical target job titles for this candidate. Use "
        "industry-standard titles for whatever profession their resume "
        "indicates. Examples across professions: 'Product Manager', "
        "'Senior Backend Engineer', 'Marketing Manager', 'Brand Designer', "
        "'Financial Analyst', 'Operations Manager', 'Customer Success "
        "Manager', 'UX Researcher', 'Nurse Practitioner', 'Tax Accountant', "
        "'Senior Recruiter', etc. Be specific - 'Engineer' or 'Manager' "
        "alone is too broad; include the function (Backend Engineer, "
        "Marketing Manager).\n\n"
        "Match the candidate's actual background. Do NOT default to tech "
        "roles unless their resume is clearly tech. If their resume is in "
        "finance, suggest finance roles. If marketing, suggest marketing "
        "roles. If healthcare, suggest healthcare roles.\n\n"
        "These titles will filter the candidate's job inbox so precision "
        "matters.\n\n"
        f"Headline: {profile.headline or '(none)'}\n"
        f"Recent roles: {'; '.join(recent_titles) or '(none)'}\n"
        f"Skills: {', '.join(skills) or '(none)'}"
    )

    suggest_tool = {
        "name": "suggest_roles",
        "description": "Suggest 2-3 canonical target job titles",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_roles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-3 specific canonical job titles.",
                }
            },
            "required": ["target_roles"],
        },
    }

    try:
        result = await llm_client.generate_structured(
            task_type="parsing",
            system_prompt="You suggest precise canonical job titles based on a candidate's profile.",
            user_prompt=prompt,
            tools=[suggest_tool],
            max_tokens=400,
        )
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("auto_suggest_roles LLM failed: %s", e)
        return {"suggested": [], "applied": False, "reason": "llm_error"}

    suggested = result.get("target_roles") or []
    suggested = [s.strip() for s in suggested if s and s.strip()]
    if not suggested:
        return {"suggested": [], "applied": False, "reason": "empty_suggestion"}

    profile.target_roles = suggested
    await db.commit()

    # Now that target_roles is set, rescore everything so the inbox
    # reflects the corrected intent (PM path only, AI titles excluded).
    from app.workers.scoring_tasks import _batch_score_async
    try:
        await _batch_score_async(str(user_id), rescore_all=True)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("Rescore after auto-suggest failed: %s", e)

    return {"suggested": suggested, "applied": True, "reason": "ok"}


@router.get("/work-history", response_model=list[WorkHistoryResponse])
async def list_work_history(user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    result = await db.execute(
        select(CandidateWorkHistory)
        .where(CandidateWorkHistory.profile_id == profile.id)
        .order_by(CandidateWorkHistory.sort_order)
    )
    return result.scalars().all()


@router.post("/work-history", response_model=WorkHistoryResponse, status_code=status.HTTP_201_CREATED)
async def add_work_history(data: WorkHistoryCreate, user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    entry = CandidateWorkHistory(profile_id=profile.id, **data.model_dump())
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/work-history/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_history(entry_id: UUID, user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    await db.execute(
        delete(CandidateWorkHistory).where(
            CandidateWorkHistory.id == entry_id,
            CandidateWorkHistory.profile_id == profile.id,
        )
    )
    await db.commit()


# ── Skills ───────────────────────────────────────────────────────────────────


@router.get("/skills", response_model=list[SkillResponse])
async def list_skills(user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    result = await db.execute(
        select(CandidateSkill).where(CandidateSkill.profile_id == profile.id)
    )
    return result.scalars().all()


@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def add_skill(data: SkillCreate, user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    skill = CandidateSkill(profile_id=profile.id, **data.model_dump())
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    return skill


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: UUID, user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    await db.execute(
        delete(CandidateSkill).where(
            CandidateSkill.id == skill_id,
            CandidateSkill.profile_id == profile.id,
        )
    )
    await db.commit()


# ── Bullet Bank ──────────────────────────────────────────────────────────────


@router.get("/bullet-bank", response_model=list[BulletResponse])
async def list_bullets(user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    result = await db.execute(
        select(CandidateBullet)
        .where(CandidateBullet.profile_id == profile.id)
        .order_by(CandidateBullet.created_at.desc())
    )
    return result.scalars().all()


@router.post("/bullet-bank", response_model=BulletResponse, status_code=status.HTTP_201_CREATED)
async def add_bullet(data: BulletCreate, user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    bullet = CandidateBullet(profile_id=profile.id, **data.model_dump())
    db.add(bullet)
    await db.commit()
    await db.refresh(bullet)
    return bullet


@router.put("/bullet-bank/{bullet_id}", response_model=BulletResponse)
async def update_bullet(
    bullet_id: UUID, data: BulletCreate, user_id: CurrentUserId, db: DbSession
):
    profile = await _get_profile(user_id, db)
    result = await db.execute(
        select(CandidateBullet).where(
            CandidateBullet.id == bullet_id,
            CandidateBullet.profile_id == profile.id,
        )
    )
    bullet = result.scalar_one_or_none()
    if not bullet:
        raise HTTPException(status_code=404, detail="Bullet not found")

    for field, value in data.model_dump().items():
        setattr(bullet, field, value)
    await db.commit()
    await db.refresh(bullet)
    return bullet


@router.delete("/bullet-bank/{bullet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bullet(bullet_id: UUID, user_id: CurrentUserId, db: DbSession):
    profile = await _get_profile(user_id, db)
    await db.execute(
        delete(CandidateBullet).where(
            CandidateBullet.id == bullet_id,
            CandidateBullet.profile_id == profile.id,
        )
    )
    await db.commit()


# ── Resumes ──────────────────────────────────────────────────────────────────


@router.get("/resumes", response_model=list[ResumeResponse])
async def list_resumes(user_id: CurrentUserId, db: DbSession):
    result = await db.execute(
        select(Resume)
        .where(Resume.user_id == user_id)
        .order_by(Resume.created_at.desc())
    )
    return result.scalars().all()


@router.post("/resumes", response_model=ResumeResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    user_id: CurrentUserId,
    db: DbSession,
    file: UploadFile = File(...),
    version_name: str = Form(...),
    tags: str = Form(""),
):
    # Validate file type
    allowed_types = {"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are accepted")

    ext = "pdf" if "pdf" in (file.content_type or "") else "docx"

    # Read file content
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    # Upload to Supabase Storage
    from app.services.storage import upload_file
    file_url = await upload_file(
        bucket="resumes",
        path=f"{user_id}/{file.filename}",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    resume = Resume(
        user_id=user_id,
        version_name=version_name,
        tags=tag_list,
        source_type=ext,
        file_url=file_url,
    )
    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    # Parse synchronously inside the request — production has no Celery
    # worker, so .delay() would silently no-op. The Anthropic call takes
    # ~10–15s which fits well within Vercel's 60s function timeout.
    # We swallow exceptions so a flaky parse doesn't roll back the upload
    # itself; the user can hit "Re-parse" later.
    from app.workers.parsing_tasks import _parse_resume_async
    try:
        await _parse_resume_async(str(resume.id), str(user_id))
        await db.refresh(resume)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("Resume parse failed: %s", e)

    # Full rescore against the freshly-parsed profile. Resume parsing
    # wipes + rebuilds work_history / skills / bullets, so any existing
    # JobScore rows reflect a stale profile and must be recomputed.
    # Pure deterministic compute (no LLM calls) — 1.7k jobs scores in
    # ~3s, well inside the Vercel 60s budget alongside the LLM parse.
    from app.workers.scoring_tasks import _batch_score_async
    try:
        await _batch_score_async(str(user_id), rescore_all=True)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).error("Initial scoring after upload failed: %s", e)

    return resume


@router.post("/rescore")
async def rescore_inbox(user_id: CurrentUserId, db: DbSession):
    """Wipe and recompute every JobScore for the current user. Use this
    when the scorer logic changes or after correcting target_roles —
    older scores would otherwise stay stale forever (the cron only
    scores newly-discovered jobs)."""
    from app.workers.scoring_tasks import _batch_score_async
    await _batch_score_async(str(user_id), rescore_all=True)
    return {"status": "complete"}


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: UUID, user_id: CurrentUserId, db: DbSession):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # NULL the FK on any TailoredApplication referencing this resume —
    # base_resume_id has no ON DELETE behavior set, so without this the
    # delete fails with a foreign-key violation as soon as the user has
    # generated even one tailored application using this resume. Profile
    # data (work_history / skills / bullets) is FK'd to candidate_profiles
    # so it's untouched, which is what we want — the parsed structure
    # survives even when the source file is removed.
    from sqlalchemy import update
    from app.models.tailoring import TailoredApplication
    await db.execute(
        update(TailoredApplication)
        .where(TailoredApplication.base_resume_id == resume_id)
        .values(base_resume_id=None)
    )

    await db.delete(resume)
    await db.commit()


@router.post("/resumes/{resume_id}/parse")
async def trigger_parse(resume_id: UUID, user_id: CurrentUserId, db: DbSession):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    from app.workers.parsing_tasks import _parse_resume_async
    await _parse_resume_async(str(resume.id), str(user_id))
    return {"status": "complete", "resume_id": str(resume_id)}


# ── Sample Applications (style training) ────────────────────────────────────


_VALID_SAMPLE_KINDS = {"cover_letter", "outreach", "summary"}
_MAX_SAMPLES_PER_KIND = 5
_MAX_SAMPLE_CHARS = 8000


class SampleApplicationCreate(BaseModel):
    kind: str = Field(..., description="cover_letter | outreach | summary")
    label: str | None = Field(None, max_length=200)
    content: str = Field(..., min_length=20, max_length=_MAX_SAMPLE_CHARS)


class SampleApplicationResponse(BaseModel):
    id: str
    kind: str
    label: str | None
    content: str
    created_at: str


def _sample_to_dict(s: SampleApplication) -> dict:
    return {
        "id": str(s.id),
        "kind": s.kind,
        "label": s.label,
        "content": s.content,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("/sample-applications")
async def list_sample_applications(user_id: CurrentUserId, db: DbSession):
    """List the user's writing samples, newest first. Tailor service uses
    these to mimic the candidate's voice when generating new drafts."""
    result = await db.execute(
        select(SampleApplication)
        .where(SampleApplication.user_id == user_id)
        .order_by(SampleApplication.created_at.desc())
    )
    return [_sample_to_dict(s) for s in result.scalars().all()]


@router.post("/sample-applications", status_code=status.HTTP_201_CREATED)
async def create_sample_application(
    data: SampleApplicationCreate,
    user_id: CurrentUserId,
    db: DbSession,
):
    """Add a writing sample (cover letter / outreach / summary). Capped
    at 5 per kind so the prompt context stays bounded — pruning the
    oldest sample of that kind when the cap is hit, so saving new ones
    feels natural ('replace my oldest example')."""
    if data.kind not in _VALID_SAMPLE_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"kind must be one of {sorted(_VALID_SAMPLE_KINDS)}",
        )

    count_result = await db.execute(
        select(SampleApplication)
        .where(
            SampleApplication.user_id == user_id,
            SampleApplication.kind == data.kind,
        )
        .order_by(SampleApplication.created_at.asc())
    )
    existing = list(count_result.scalars().all())
    if len(existing) >= _MAX_SAMPLES_PER_KIND:
        # Drop the oldest so the new one fits inside the cap.
        await db.delete(existing[0])
        await db.flush()

    sample = SampleApplication(
        user_id=user_id,
        kind=data.kind,
        label=(data.label or None),
        content=data.content.strip(),
    )
    db.add(sample)
    await db.commit()
    await db.refresh(sample)
    return _sample_to_dict(sample)


@router.delete(
    "/sample-applications/{sample_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_sample_application(
    sample_id: UUID, user_id: CurrentUserId, db: DbSession
):
    result = await db.execute(
        select(SampleApplication).where(
            SampleApplication.id == sample_id,
            SampleApplication.user_id == user_id,
        )
    )
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    await db.delete(sample)
    await db.commit()


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_profile(user_id: UUID, db) -> CandidateProfile:
    result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Create a profile first")
    return profile
