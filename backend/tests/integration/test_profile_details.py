"""Users correct what resume parsing got wrong: add, edit and remove roles
and skills, only on their own profile."""

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000b601")
OTHER = uuid.UUID("00000000-0000-0000-0000-00000000b602")


@pytest.fixture
async def client():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE candidate_skills, candidate_work_history, candidate_profiles, users CASCADE"))
        for user in (USER, OTHER):
            await conn.execute(text("INSERT INTO users (id, email, name, role) VALUES (:u, :e, 'P', 'user')"),
                               {"u": user, "e": f"{user}@test.dev"})
            await conn.execute(text("INSERT INTO candidate_profiles (id, user_id) VALUES (gen_random_uuid(), :u)"), {"u": user})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def test_roles_can_be_added_edited_and_removed(client):
    old = (await client.post("/api/v1/candidates/work-history", json={
        "company": " Fintech Co ", "title": "Automation Engineer", "start_date": "2019-01-01", "end_date": "2021-06-01",
        "bullets": ["Built workflows", "  ", ""],
    })).json()
    assert old["company"] == "Fintech Co" and old["bullets"] == ["Built workflows"]
    current = (await client.post("/api/v1/candidates/work-history", json={
        "company": "Acme", "title": "AI Engineer", "start_date": "2021-07-01",
    })).json()

    roles = (await client.get("/api/v1/candidates/work-history")).json()
    # The current role comes first: scoring reads it as the candidate's level.
    assert [r["title"] for r in roles] == ["AI Engineer", "Automation Engineer"]

    r = await client.put(f"/api/v1/candidates/work-history/{current['id']}", json={"title": "Senior AI Engineer", "bullets": ["Shipped agents"]})
    assert r.status_code == 200 and r.json()["title"] == "Senior AI Engineer" and r.json()["company"] == "Acme"
    # Ending the current role before the other one moves it down.
    await client.put(f"/api/v1/candidates/work-history/{current['id']}", json={"end_date": "2021-08-01"})
    await client.put(f"/api/v1/candidates/work-history/{old['id']}", json={"end_date": None})
    assert [r["title"] for r in (await client.get("/api/v1/candidates/work-history")).json()] == ["Automation Engineer", "Senior AI Engineer"]

    assert (await client.put(f"/api/v1/candidates/work-history/{old['id']}", json={"end_date": "2018-01-01"})).status_code == 422
    assert (await client.post("/api/v1/candidates/work-history", json={"company": "", "title": "X"})).status_code == 422

    # Someone else's role can't be changed or removed.
    other = {"x-test-user": str(OTHER)}
    assert (await client.put(f"/api/v1/candidates/work-history/{old['id']}", json={"title": "Hacked"}, headers=other)).status_code == 404
    assert (await client.delete(f"/api/v1/candidates/work-history/{old['id']}", headers=other)).status_code == 404

    assert (await client.delete(f"/api/v1/candidates/work-history/{old['id']}")).status_code == 204
    assert [r["title"] for r in (await client.get("/api/v1/candidates/work-history")).json()] == ["Senior AI Engineer"]


async def test_skills_can_be_added_and_removed(client):
    r = await client.post("/api/v1/candidates/skills", json={"skill_name": "  LangChain ", "category": "tool"})
    assert r.status_code == 201 and r.json()["skill_name"] == "LangChain"
    assert (await client.post("/api/v1/candidates/skills", json={"skill_name": "langchain", "category": "technical"})).status_code == 409
    assert (await client.post("/api/v1/candidates/skills", json={"skill_name": "Python", "category": "wizardry"})).status_code == 422
    skill_id = r.json()["id"]
    assert (await client.delete(f"/api/v1/candidates/skills/{skill_id}", headers={"x-test-user": str(OTHER)})).status_code == 204
    assert len((await client.get("/api/v1/candidates/skills")).json()) == 1  # still there: not theirs
    assert (await client.delete(f"/api/v1/candidates/skills/{skill_id}")).status_code == 204
    assert (await client.get("/api/v1/candidates/skills")).json() == []
