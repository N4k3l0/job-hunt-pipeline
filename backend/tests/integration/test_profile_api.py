"""Profile preferences that grading depends on are actually saved."""

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000d001")


@pytest.fixture
async def client():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE candidate_profiles, jobs, users CASCADE"))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:id, 'p@test.dev', 'P', 'user')"
        ), {"id": USER})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"x-test-user": str(USER)}) as c:
        yield c
    app.dependency_overrides.clear()


async def test_preferences_round_trip(client):
    r = await client.post("/api/v1/candidates/profile", json={"preferred_countries": ["GB"], "home_country": "ng"})
    assert r.status_code == 201, r.text
    assert r.json()["home_country"] == "NG"

    r = await client.put("/api/v1/candidates/profile", json={
        "search_keywords": ["fintech product manager"],
        "blocked_sources": ["remoteok"],
        "salary_min": 90000,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["search_keywords"] == ["fintech product manager"]
    assert body["blocked_sources"] == ["remoteok"]
    assert body["salary_min"] == 90000
    assert body["home_country"] == "NG"  # untouched by a partial update

    # Explicit null clears a value.
    r = await client.put("/api/v1/candidates/profile", json={"salary_min": None})
    assert r.json()["salary_min"] is None
    assert r.json()["search_keywords"] == ["fintech product manager"]


async def test_home_country_must_be_a_real_code(client):
    r = await client.post("/api/v1/candidates/profile", json={"home_country": "WW"})
    assert r.status_code == 422
