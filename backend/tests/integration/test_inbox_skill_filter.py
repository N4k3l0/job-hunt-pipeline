"""The inbox keeps jobs whose title doesn't match the user's roles when
scoring found the user's skills in them, without scanning descriptions."""

import uuid
from datetime import datetime, timezone

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000d001")
TITLE_MATCH = uuid.UUID("50000000-0000-0000-0000-000000000001")
SKILL_IN_DESCRIPTION = uuid.UUID("50000000-0000-0000-0000-000000000002")
UNRELATED = uuid.UUID("50000000-0000-0000-0000-000000000003")


@pytest.fixture
async def client():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE user_job_states, application_tracking, job_scores, candidate_skills, "
            "candidate_profiles, jobs, users CASCADE"
        ))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:u, 'd@test.dev', 'D', 'user')"
        ), {"u": USER})
        profile_id = (await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference) "
            "VALUES (gen_random_uuid(), :u, ARRAY['Product Manager'], 'any') RETURNING id"
        ), {"u": USER})).scalar()
        await conn.execute(text(
            "INSERT INTO candidate_skills (id, profile_id, skill_name, category) "
            "VALUES (gen_random_uuid(), :p, 'Figma', 'tool')"
        ), {"p": profile_id})
        now = datetime.now(timezone.utc)
        for job_id, title, description in (
            (TITLE_MATCH, "Product Manager", "Own the roadmap."),
            (SKILL_IN_DESCRIPTION, "Visual Designer", "You will design flows in Figma every day."),
            (UNRELATED, "Warehouse Associate", "Move boxes safely."),
        ):
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, remote_type, raw_description, status, discovered_at) "
                "VALUES (:id, 'Acme', :title, 'full_remote', :desc, 'enriched', :now)"
            ), {"id": job_id, "title": title, "desc": description, "now": now})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def _inbox(client) -> set[str]:
    r = await client.get("/api/v1/jobs", params={"min_score": 0})
    assert r.status_code == 200, r.text
    return {j["id"] for j in r.json()["jobs"]}


async def test_skill_matches_come_from_scores(client):
    # Before scoring, only the title match qualifies.
    assert await _inbox(client) == {str(TITLE_MATCH)}

    r = await client.post("/api/v1/candidates/rescore")
    assert r.status_code == 200, r.text

    inbox = await _inbox(client)
    assert inbox == {str(TITLE_MATCH), str(SKILL_IN_DESCRIPTION)}

    overview = (await client.get("/api/v1/analytics/overview")).json()
    assert overview["jobs_discovered"] == len(inbox)
