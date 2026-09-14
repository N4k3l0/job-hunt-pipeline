"""The inbox's default order favours fresh jobs: scores count in full for a
week, then drop a point a day, up to 25 points."""

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000e101")
NOW = datetime.now(timezone.utc)

# title: (score, discovered days ago, posted days ago or None)
JOBS = {
    "Old strong match": (90, 60, None),        # 90 - 25 = 65
    "New good match": (75, 1, None),           # 75
    "Ten days old": (80, 10, None),            # 80 - 3 = 77
    "Old posting found this week": (85, 3, 50),  # 85 - 25 = 60
}


@pytest.fixture
async def client():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE user_job_states, application_tracking, job_scores, candidate_skills, "
            "candidate_profiles, jobs, job_sources, users CASCADE"
        ))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:u, 'fresh@test.dev', 'F', 'user')"
        ), {"u": USER})
        await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference) "
            "VALUES (gen_random_uuid(), :u, ARRAY['Analyst'], 'any')"
        ), {"u": USER})
        for title, (score, discovered, posted) in JOBS.items():
            job_id = uuid.uuid4()
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, remote_type, status, discovered_at, posted_at) "
                "VALUES (:id, 'Acme', :title, 'full_remote', 'scored', :d, :p)"
            ), {
                "id": job_id, "title": f"Analyst: {title}",
                "d": NOW - timedelta(days=discovered),
                "p": NOW - timedelta(days=posted) if posted else None,
            })
            await conn.execute(text(
                "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, "
                "seniority_score, industry_score, geo_score, remote_score, salary_score, visa_score, "
                "overall_fit, priority, score_version) "
                "VALUES (gen_random_uuid(), :j, :u, 'general', 0, 0, 0, 0, 0, 0, 0, 0, :fit, 'medium', 2)"
            ), {"j": job_id, "u": USER, "fit": score})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def _titles(client, **params):
    r = await client.get("/api/v1/jobs", params=params)
    assert r.status_code == 200, r.text
    return [j["title"].removeprefix("Analyst: ") for j in r.json()["jobs"]]


async def test_default_order_favours_fresh_jobs(client):
    assert await _titles(client) == [
        "Ten days old", "New good match", "Old strong match", "Old posting found this week",
    ]
    assert await _titles(client, sort_by="best") == await _titles(client)

    # Score alone is still available.
    assert await _titles(client, sort_by="score") == [
        "Old strong match", "Old posting found this week", "Ten days old", "New good match",
    ]
