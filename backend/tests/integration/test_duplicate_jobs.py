"""Duplicates: the same job twice in one discovery batch is stored once, and
postings of one job (several cities or sources) show once in the inbox."""

import uuid
from datetime import datetime, timedelta, timezone

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000d201")
NOW = datetime.now(timezone.utc)


async def _reset(conn):
    await conn.execute(text(
        "TRUNCATE user_job_states, application_tracking, job_scores, candidate_skills, "
        "candidate_profiles, jobs, job_sources, users CASCADE"
    ))


async def test_same_job_twice_in_one_batch_is_stored_once():
    from app.core.database import engine
    from app.workers.discovery_tasks import _ingest_raw_jobs

    async with engine.begin() as conn:
        await _reset(conn)

    base = {"source_name": "remotive", "company": "Lemon.io", "title": "Senior Data Engineer",
            "location": "Remote", "raw_description": ""}
    await _ingest_raw_jobs([
        {**base, "job_url": "https://jobs.example.com/a"},
        {**base, "job_url": "https://jobs.example.com/b"},        # same fingerprint
        {**base, "title": "Data Engineer", "job_url": "https://jobs.example.com/a"},  # same URL
        {**base, "title": "Staff Data Engineer", "job_url": "https://jobs.example.com/c"},
    ])

    async with engine.connect() as conn:
        titles = sorted((await conn.execute(text("SELECT title FROM jobs"))).scalars())
    assert titles == ["Senior Data Engineer", "Staff Data Engineer"]


@pytest.fixture
async def client():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async with engine.begin() as conn:
        await _reset(conn)
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:u, 'dup@test.dev', 'D', 'user')"
        ), {"u": USER})
        await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference) "
            "VALUES (gen_random_uuid(), :u, ARRAY['Architect'], 'any')"
        ), {"u": USER})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def _job(company, title, location, score, days_old=1) -> uuid.UUID:
    from app.core.database import engine

    job_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, location, remote_type, status, discovered_at) "
            "VALUES (:id, :company, :title, :location, 'full_remote', 'scored', :d)"
        ), {"id": job_id, "company": company, "title": title, "location": location,
            "d": NOW - timedelta(days=days_old)})
        await conn.execute(text(
            "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, "
            "seniority_score, industry_score, geo_score, remote_score, salary_score, visa_score, "
            "overall_fit, priority, score_version) "
            "VALUES (gen_random_uuid(), :j, :u, 'general', 0, 0, 0, 0, 0, 0, 0, 0, :fit, 'medium', 2)"
        ), {"j": job_id, "u": USER, "fit": score})
    return job_id


async def test_postings_of_one_job_show_once(client):
    madrid = await _job("Anthropic", "Applied AI Architect", "Madrid, Spain", 80)
    london = await _job("Anthropic", "Applied AI Architect", "London, UK", 85)
    await _job("anthropic ", "applied ai architect", "Seoul", 70)  # same job, different casing
    other = await _job("Anthropic", "Applied AI Architect, Industries", "London, UK", 75)
    single = await _job("Figma", "Solutions Architect", "Remote", 60)

    r = await client.get("/api/v1/jobs")
    body = r.json()
    assert [j["id"] for j in body["jobs"]] == [str(london), str(other), str(single)]
    assert body["total"] == 3
    assert [j["other_postings"] for j in body["jobs"]] == [2, 0, 0]

    # Pages and totals agree.
    r = await client.get("/api/v1/jobs", params={"page": 2, "page_size": 2})
    assert r.json()["total"] == 3 and [j["id"] for j in r.json()["jobs"]] == [str(single)]
    r = await client.get("/api/v1/jobs", params={"page": 3, "page_size": 2})
    assert r.json() == {"jobs": [], "total": 3, "page": 3, "page_size": 2}

    overview = (await client.get("/api/v1/analytics/overview")).json()
    assert overview["jobs_discovered"] == 3

    # Applying to one posting hides the job's other postings too.
    from app.core.database import engine
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO application_tracking (id, job_id, user_id, status) VALUES (gen_random_uuid(), :j, :u, 'applied')"
        ), {"j": madrid, "u": USER})
    r = await client.get("/api/v1/jobs")
    assert [j["id"] for j in r.json()["jobs"]] == [str(other), str(single)]
