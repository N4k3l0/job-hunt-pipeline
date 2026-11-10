"""Clearing the Closed column of the Applications board: the cards are
hidden, kept in the database, and Undo puts them back."""

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

ME = uuid.UUID("00000000-0000-0000-0000-00000000c001")
CARDS = [uuid.UUID(f"60000000-0000-0000-0000-{n:012d}") for n in range(1, 4)]


async def test_cleared_cards_are_hidden_and_undo_brings_them_back():
    from app.api.deps import DbSession, get_current_user
    from app.core.database import engine
    from app.main import app
    from app.models.user import User

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE users CASCADE"))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role, preferences) "
            "VALUES (:me, 'me@test.dev', 'Me', 'user', '{\"career_level\": \"mid\"}')"
        ), {"me": ME})

    async def me(db: DbSession) -> User:
        return await db.get(User, ME)

    app.dependency_overrides[get_current_user] = me
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/api/v1/tracking/cleared")).json() == {"ids": []}

            ids = [str(c) for c in CARDS]
            assert (await client.post("/api/v1/tracking/cleared", json={"ids": ids[:2]})).json()["ids"] == ids[:2]
            # Clearing again adds only the new ones.
            assert (await client.post("/api/v1/tracking/cleared", json={"ids": ids})).json()["ids"] == ids
            assert (await client.get("/api/v1/tracking/cleared")).json()["ids"] == ids

            back = await client.post("/api/v1/tracking/cleared/restore", json={"ids": [ids[1]]})
            assert back.json()["ids"] == [ids[0], ids[2]]

            bad = await client.post("/api/v1/tracking/cleared", json={"ids": ["not-an-id"]})
            assert bad.status_code == 422
    finally:
        app.dependency_overrides.clear()

    # Other settings are untouched.
    async with engine.begin() as conn:
        prefs = (await conn.execute(text("SELECT preferences FROM users WHERE id = :me"), {"me": ME})).scalar_one()
    assert prefs["career_level"] == "mid"
    assert prefs["cleared_from_board"] == [str(CARDS[0]), str(CARDS[2])]
