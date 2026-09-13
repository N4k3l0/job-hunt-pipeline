"""End-to-end checks against a real Postgres: one user's shortlist,
dismiss and applied actions must not change another user's inbox, the
Worldwide preference must not shrink the inbox, and invite requests must
be stored. Skipped unless TEST_DATABASE_URL is set (see tests/conftest.py).
"""

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

USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
JOB_REMOTE = uuid.UUID("20000000-0000-0000-0000-000000000001")
JOB_BR = uuid.UUID("20000000-0000-0000-0000-000000000002")
JOB_NL = uuid.UUID("20000000-0000-0000-0000-000000000003")


@pytest.fixture
async def client():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE user_job_states, application_tracking, job_scores, "
            "candidate_profiles, invite_requests, jobs, users CASCADE"
        ))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES "
            "(:a, 'a@test.dev', 'A', 'user'), (:b, 'b@test.dev', 'B', 'user')"
        ), {"a": USER_A, "b": USER_B})
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, location, country, remote_type, status) VALUES "
            "(:remote, 'Acme', 'Product Manager', 'Remote', NULL, 'full_remote', 'scored'), "
            "(:br, 'Beta', 'Product Manager', 'São Paulo, Brazil', 'BR', 'hybrid', 'scored'), "
            "(:nl, 'Gamma', 'Product Manager', 'Amsterdam, Netherlands', 'NL', 'onsite', 'scored')"
        ), {"remote": JOB_REMOTE, "br": JOB_BR, "nl": JOB_NL})

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def _as(user: uuid.UUID) -> dict:
    return {"x-test-user": str(user)}


async def _inbox(client, user, **params) -> dict[str, str]:
    r = await client.get("/api/v1/jobs", params={"min_score": 0, **params}, headers=_as(user))
    assert r.status_code == 200, r.text
    return {j["id"]: j["status"] for j in r.json()["jobs"]}


async def _set_countries(client, user, countries):
    r = await client.post(
        "/api/v1/candidates/profile",
        json={"preferred_countries": countries},
        headers=_as(user),
    )
    assert r.status_code in (200, 201), r.text


async def test_shortlist_is_per_user(client):
    r = await client.post(f"/api/v1/jobs/{JOB_REMOTE}/shortlist", headers=_as(USER_A))
    assert r.status_code == 200

    assert (await _inbox(client, USER_A))[str(JOB_REMOTE)] == "shortlisted"
    assert (await _inbox(client, USER_B))[str(JOB_REMOTE)] == "scored"
    assert list(await _inbox(client, USER_A, status="shortlisted")) == [str(JOB_REMOTE)]
    assert await _inbox(client, USER_B, status="shortlisted") == {}

    overview_a = (await client.get("/api/v1/analytics/overview", headers=_as(USER_A))).json()
    overview_b = (await client.get("/api/v1/analytics/overview", headers=_as(USER_B))).json()
    assert overview_a["jobs_shortlisted"] == 1
    assert overview_b["jobs_shortlisted"] == 0

    r = await client.post(f"/api/v1/jobs/{JOB_REMOTE}/unshortlist", headers=_as(USER_A))
    assert r.json()["status"] == "scored"
    assert (await _inbox(client, USER_A))[str(JOB_REMOTE)] == "scored"


async def test_dismiss_is_per_user(client):
    r = await client.post(f"/api/v1/jobs/{JOB_REMOTE}/dismiss", headers=_as(USER_A))
    assert r.status_code == 200

    assert str(JOB_REMOTE) not in await _inbox(client, USER_A)
    assert str(JOB_REMOTE) in await _inbox(client, USER_B)

    # Dismissing after shortlisting replaces the state rather than adding a row.
    await client.post(f"/api/v1/jobs/{JOB_NL}/shortlist", headers=_as(USER_A))
    await client.post(f"/api/v1/jobs/{JOB_NL}/dismiss", headers=_as(USER_A))
    assert str(JOB_NL) not in await _inbox(client, USER_A)


async def test_mark_applied_is_per_user(client):
    r = await client.post(f"/api/v1/jobs/{JOB_NL}/mark-applied", headers=_as(USER_A))
    assert r.status_code == 200

    assert str(JOB_NL) not in await _inbox(client, USER_A)
    assert (await _inbox(client, USER_A, include_applied="true"))[str(JOB_NL)] == "applied"
    assert (await _inbox(client, USER_B))[str(JOB_NL)] == "scored"

    detail_a = (await client.get(f"/api/v1/jobs/{JOB_NL}", headers=_as(USER_A))).json()
    detail_b = (await client.get(f"/api/v1/jobs/{JOB_NL}", headers=_as(USER_B))).json()
    assert detail_a["status"] == "applied"
    assert detail_b["status"] == "scored"

    await client.post(f"/api/v1/jobs/{JOB_NL}/unmark-applied", headers=_as(USER_A))
    assert (await _inbox(client, USER_A))[str(JOB_NL)] == "scored"


async def test_worldwide_does_not_shrink_inbox(client):
    await _set_countries(client, USER_A, ["WW"])
    await _set_countries(client, USER_B, ["NL"])

    assert set(await _inbox(client, USER_A)) == {str(JOB_REMOTE), str(JOB_BR), str(JOB_NL)}
    assert set(await _inbox(client, USER_B)) == {str(JOB_REMOTE), str(JOB_NL)}


async def test_invite_requests_are_stored_once(client):
    from app.core.database import engine

    for email in ("Someone@Example.com", "someone@example.com"):
        r = await client.post("/api/v1/invite-requests", json={"email": email, "source": "hero"})
        assert r.status_code == 201, r.text

    r = await client.post("/api/v1/invite-requests", json={"email": "nope"})
    assert r.status_code == 422

    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT email, source FROM invite_requests"))).all()
    assert rows == [("someone@example.com", "hero")]
