from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class JobBase(BaseModel):
    company: str
    title: str
    location: str | None = None
    country: str | None = None
    remote_type: str | None = None
    job_url: str | None = None
    apply_url: str | None = None
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    application_type: str | None = None


class JobResponse(JobBase):
    id: UUID
    source_name: str | None = None
    status: str
    discovered_at: datetime
    expires_at: datetime | None = None

    model_config = {"from_attributes": True}


class JobDetailResponse(JobResponse):
    raw_description: str | None = None
    entities: "JobEntityResponse | None" = None
    score: "JobScoreResponse | None" = None


class JobEntityResponse(BaseModel):
    skills: list[str] | None = None
    requirements: list[str] | None = None
    keywords: list[str] | None = None
    nice_to_have: list[str] | None = None
    visa_notes: str | None = None
    sponsorship_available: bool | None = None
    application_questions: list[str] | None = None
    years_experience_min: int | None = None
    years_experience_max: int | None = None

    model_config = {"from_attributes": True}


class JobScoreResponse(BaseModel):
    role_path: str
    title_score: float
    skill_score: float
    seniority_score: float
    industry_score: float
    geo_score: float
    remote_score: float
    salary_score: float
    visa_score: float
    overall_fit: float
    priority: str
    reasoning: dict | None = None
    calculated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int
    page: int
    page_size: int


class TailoredApplicationResponse(BaseModel):
    id: UUID
    job_id: UUID
    tailored_summary: str | None = None
    cover_letter: str | None = None
    recruiter_message: str | None = None
    short_answers: dict | None = None
    keyword_matches: dict | None = None
    validation_notes: dict | None = None
    approval_status: str
    tailored_resume_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TailoredApplicationUpdate(BaseModel):
    tailored_summary: str | None = None
    cover_letter: str | None = None
    recruiter_message: str | None = None
    short_answers: dict | None = None
