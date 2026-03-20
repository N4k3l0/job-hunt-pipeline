from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, status
from sqlalchemy import select, delete
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUserId, DbSession
from app.models.candidate import (
    CandidateProfile,
    CandidateWorkHistory,
    CandidateSkill,
    CandidateEducation,
    CandidateBullet,
    Resume,
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

    # Score all existing jobs for this new profile
    from app.workers.scoring_tasks import batch_score_for_user
    batch_score_for_user.delay(str(user_id))

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
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)
    return profile


# ── Work History ─────────────────────────────────────────────────────────────


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

    # Queue parsing task
    from app.workers.parsing_tasks import parse_resume
    parse_resume.delay(str(resume.id), str(user_id))

    return resume


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: UUID, user_id: CurrentUserId, db: DbSession):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
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

    from app.workers.parsing_tasks import parse_resume
    parse_resume.delay(str(resume.id), str(user_id))
    return {"status": "queued", "resume_id": str(resume_id)}


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_profile(user_id: UUID, db) -> CandidateProfile:
    result = await db.execute(
        select(CandidateProfile).where(CandidateProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Create a profile first")
    return profile
