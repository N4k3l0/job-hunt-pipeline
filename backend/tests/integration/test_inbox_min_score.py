"""The inbox's minimum score: jobs below it are hidden, unscored manual
imports still show, and the count matches the rows across pages."""

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000e001")
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-00000000e002")


def job_id(n: int) -> uuid.UUID:
    return uuid.UUID(f"60000000-0000-0000-0000-{n:012d}")


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
        for user in (USER, OTHER_USER):
            await conn.execute(text(
                "INSERT INTO users (id, email, name, role) VALUES (:u, :e, 'E', 'user')"
            ), {"u": user, "e": f"{user}@test.dev"})
        await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference) "
            "VALUES (gen_random_uuid(), :u, ARRAY['Data Analyst', 'BI Developer'], 'any')"
        ), {"u": USER})
        manual = uuid.uuid4()
        await conn.execute(text(
            "INSERT INTO job_sources (id, name, source_type, is_active) VALUES (:id, 'manual', 'manual', true)"
        ), {"id": manual})

        now = datetime.now(timezone.utc)
        # (n, title, this user's score or None, source)
        jobs = [
            (1, "Senior Data Analyst", 90, None),
            (2, "Data Analyst", 70, None),
            (3, "BI Developer", 55, None),
            (4, "Data Analyst II", 40, None),        # below the minimum
            (5, "Data Analyst, Imported", None, manual),  # manual, not scored yet
            (6, "Data Analyst (cron)", None, None),  # not scored, not manual
            (7, "Warehouse Associate", 95, None),    # high score, title doesn't match
        ]
        for n, title, score, source in jobs:
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, remote_type, status, discovered_at, source_id) "
                "VALUES (:id, 'Acme', :title, 'full_remote', 'scored', :at, :source)"
            ), {"id": job_id(n), "title": title, "at": now - timedelta(minutes=n), "source": source})
            if score is not None:
                await conn.execute(text(
                    "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, "
                    "seniority_score, industry_score, geo_score, remote_score, salary_score, visa_score, "
                    "overall_fit, priority, score_version) "
                    "VALUES (gen_random_uuid(), :j, :u, 'general', 0, 0, 0, 0, 0, 0, 0, 0, :fit, 'medium', 2)"
                ), {"j": job_id(n), "u": USER, "fit": score})
        # Another user's high score doesn't count for this user.
        await conn.execute(text(
            "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, "
            "seniority_score, industry_score, geo_score, remote_score, salary_score, visa_score, "
            "overall_fit, priority, score_version) "
            "VALUES (gen_random_uuid(), :j, :u, 'general', 0, 0, 0, 0, 0, 0, 0, 0, 99, 'high', 2)"
        ), {"j": job_id(4), "u": OTHER_USER})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def test_min_score_and_manual_imports(client):
    r = await client.get("/api/v1/jobs", params={"min_score": 50, "sort_by": "score"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [j["id"] for j in body["jobs"]] == [str(job_id(1)), str(job_id(2)), str(job_id(3)), str(job_id(5))]
    assert body["total"] == 4

    # Pages agree with the total.
    seen = []
    for page in (1, 2, 3):
        r = await client.get("/api/v1/jobs", params={"min_score": 50, "page": page, "page_size": 2})
        assert r.json()["total"] == 4
        seen += [j["id"] for j in r.json()["jobs"]]
    assert sorted(seen) == sorted(str(job_id(n)) for n in (1, 2, 3, 5))

    # A lower minimum brings back the 40.
    r = await client.get("/api/v1/jobs", params={"min_score": 30})
    assert {j["id"] for j in r.json()["jobs"]} == {str(job_id(n)) for n in (1, 2, 3, 4, 5)}

    # No minimum: every title match, scored or not.
    r = await client.get("/api/v1/jobs", params={"min_score": 0})
    assert {j["id"] for j in r.json()["jobs"]} == {str(job_id(n)) for n in (1, 2, 3, 4, 5)}

    # The dashboard counts every title match, whatever the score.
    overview = (await client.get("/api/v1/analytics/overview")).json()
    assert overview["jobs_discovered"] == 6
