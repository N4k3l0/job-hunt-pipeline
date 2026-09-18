"""Country restrictions on a job, and the bad values that once emptied
every inbox: a JSON null in job_entities.eligible_countries made the whole
query fail with "cannot get array length of a scalar"."""

import uuid

import httpx
import pytest
from fastapi import Header
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

USER = uuid.UUID("00000000-0000-0000-0000-00000000f001")


def job_id(n: int) -> uuid.UUID:
    return uuid.UUID(f"70000000-0000-0000-0000-{n:012d}")


# (n, title, eligible_countries as JSON, kept for a user who can work in NG)
JOBS = [
    (1, "Data Analyst, Worldwide", None, True),           # no entity row at all
    (2, "Data Analyst, Open", "[]", True),                # stated, no restriction
    (3, "Data Analyst, Nigeria", '["NG"]', True),
    (4, "Data Analyst, US only", '["US"]', False),
    (5, "Data Analyst, Unknown", "null", True),           # the bad value
    (6, "Data Analyst, Odd", '"US"', True),               # a scalar, not a list
]


@pytest.fixture
async def client():
    from app.api.deps import get_current_user_id
    from app.core.database import engine
    from app.main import app

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE user_job_states, application_tracking, job_scores, candidate_skills, "
            "candidate_profiles, job_entities, jobs, job_sources, users CASCADE"
        ))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:u, 'f@test.dev', 'F', 'user')"
        ), {"u": USER})
        await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference, home_country) "
            "VALUES (gen_random_uuid(), :u, ARRAY['Data Analyst'], 'any', 'NG')"
        ), {"u": USER})
        for n, title, countries, _ in JOBS:
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, remote_type, status, discovered_at) "
                "VALUES (:id, 'Acme', :title, 'full_remote', 'scored', now())"
            ), {"id": job_id(n), "title": title})
            await conn.execute(text(
                "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, seniority_score, "
                "industry_score, geo_score, remote_score, salary_score, visa_score, overall_fit, priority, score_version) "
                "VALUES (gen_random_uuid(), :j, :u, 'general', 80, 10, 0, 0, 0, 0, 0, 0, 80, 'high', 2)"
            ), {"j": job_id(n), "u": USER})
            if countries is not None:
                await conn.execute(text(
                    "INSERT INTO job_entities (id, job_id, skills, requirements, keywords, eligible_countries) "
                    "VALUES (gen_random_uuid(), :j, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, CAST(:c AS jsonb))"
                ), {"j": job_id(n), "c": countries})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def test_bad_country_values_dont_empty_the_inbox(client):
    r = await client.get("/api/v1/jobs", params={"page_size": 50})
    assert r.status_code == 200, r.text
    titles = {job["title"] for job in r.json()["jobs"]}
    assert titles == {title for _, title, _, kept in JOBS if kept}
    assert r.json()["total"] == 5


async def test_a_job_without_an_entity_row_keeps_null(client):
    """The model must store "not stated" as SQL NULL, not a JSON null."""
    from app.core.database import engine
    from app.models.job import JobEntity

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM job_entities WHERE job_id = :j"), {"j": job_id(2)})

    from app.core.database import create_worker_session
    async with create_worker_session()() as db:
        db.add(JobEntity(job_id=job_id(2), skills=[], requirements=[], keywords=[], eligible_countries=None))
        await db.commit()

    async with engine.connect() as conn:
        kind = (await conn.execute(text(
            "SELECT jsonb_typeof(eligible_countries) FROM job_entities WHERE job_id = :j"
        ), {"j": job_id(2)})).scalar()
    assert kind is None
