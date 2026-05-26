from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


# Allowed remote preferences — anything outside this set means the scorer
# falls into an undefined branch. Reject garbage instead of silently
# accepting it.
_VALID_REMOTE_PREFS = {"any", "full_remote", "hybrid", "onsite"}


class ProfileBase(BaseModel):
    headline: str | None = None
    master_summary: str | None = None
    target_roles: list[str] | None = None
    preferred_countries: list[str] | None = None
    visa_statuses: dict | None = None
    remote_preference: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    links: dict | None = None

    @field_validator("preferred_countries")
    @classmethod
    def _validate_countries(cls, v: list[str] | None) -> list[str] | None:
        """Coerce to clean uppercased 2-letter ISO codes, drop garbage.
        Without this the country filter quietly tries to match things
        like 'USA' or 'United States' against Job.country='US' and finds
        nothing, so the inbox stays empty for no visible reason."""
        if not v:
            return v
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in v:
            if not isinstance(raw, str):
                continue
            code = raw.strip().upper()
            # Accept exactly 2-letter alpha codes. Special-case "WW"
            # (worldwide / remote) — UI uses it as a sentinel.
            if len(code) == 2 and code.isalpha() and code not in seen:
                cleaned.append(code)
                seen.add(code)
        return cleaned or None

    @field_validator("remote_preference")
    @classmethod
    def _validate_remote_pref(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip().lower()
        if v not in _VALID_REMOTE_PREFS:
            raise ValueError(
                f"remote_preference must be one of {sorted(_VALID_REMOTE_PREFS)}"
            )
        return v


class ProfileCreate(ProfileBase):
    pass


class ProfileUpdate(ProfileBase):
    pass


class ProfileResponse(ProfileBase):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkHistoryBase(BaseModel):
    company: str
    title: str
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = None
    bullets: list[str] | None = None
    skills: list[str] | None = None
    domain_tags: list[str] | None = None
    sort_order: int = 0


class WorkHistoryCreate(WorkHistoryBase):
    pass


class WorkHistoryResponse(WorkHistoryBase):
    id: UUID

    model_config = {"from_attributes": True}


class SkillBase(BaseModel):
    skill_name: str
    category: str | None = None
    proficiency: str | None = None
    years_experience: float | None = None


class SkillCreate(SkillBase):
    pass


class SkillResponse(SkillBase):
    id: UUID

    model_config = {"from_attributes": True}


class BulletBase(BaseModel):
    text: str
    domain_tags: list[str] | None = None
    role_tags: list[str] | None = None
    keywords: list[str] | None = None


class BulletCreate(BulletBase):
    pass


class BulletResponse(BulletBase):
    id: UUID
    used_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ResumeResponse(BaseModel):
    id: UUID
    version_name: str
    tags: list[str] | None = None
    source_type: str
    file_url: str
    parsed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
