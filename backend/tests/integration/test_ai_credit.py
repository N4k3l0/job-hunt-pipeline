"""What the app spends on AI: every call counted, what's left of the
balance the admin recorded, a warning before it runs out, and "I've
topped up" turning AI back on at once."""

import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.services.ai_credit import record_usage as real_record_usage
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

ADMIN = uuid.UUID("00000000-0000-0000-0000-0000000000ad")


@pytest.fixture
async def admin_client():
    from app.api.deps import require_admin
    from app.core.database import engine
    from app.main import app
    from app.models.user import User

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE ai_usage_hours, ai_credit_balances, users CASCADE"))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:id, 'admin@test.dev', 'Admin', 'admin')"
        ), {"id": ADMIN})
    app.dependency_overrides[require_admin] = lambda: User(id=ADMIN, email="admin@test.dev", name="Admin", role="admin")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


async def _spend(conn, when: datetime, task: str, cost: str, calls: int = 1):
    await conn.execute(text(
        "INSERT INTO ai_usage_hours (hour, task, model, calls, input_tokens, output_tokens, web_searches, cost_usd) "
        "VALUES (:hour, :task, 'claude-haiku-4-5', :calls, 0, 0, 0, :cost)"
    ), {"hour": when.replace(minute=0, second=0, microsecond=0), "task": task, "calls": calls, "cost": Decimal(cost)})


async def test_calls_in_the_same_hour_add_up(admin_client):
    from app.core.database import async_session, engine

    sonnet = SimpleNamespace(input_tokens=1000, output_tokens=500)
    await real_record_usage("review", "claude-sonnet-5", sonnet, session_factory=async_session)
    await real_record_usage("review", "claude-sonnet-5", sonnet, session_factory=async_session)
    await real_record_usage("extraction", "claude-haiku-4-5", sonnet, session_factory=async_session)
    async with engine.connect() as conn:
        rows = (await conn.execute(text(
            "SELECT task, calls, input_tokens, cost_usd FROM ai_usage_hours ORDER BY task"
        ))).all()
    assert [(r.task, r.calls, r.input_tokens, r.cost_usd) for r in rows] == [
        ("extraction", 1, 1000, Decimal("0.003500")),
        ("review", 2, 2000, Decimal("0.014000")),
    ]


async def test_counting_never_breaks_the_call():
    def broken():
        raise RuntimeError("database is down")

    # Nothing raised: the answer the model gave still reaches the user.
    await real_record_usage("review", "claude-sonnet-5", SimpleNamespace(input_tokens=1, output_tokens=1),
                            session_factory=broken)


async def test_spending_by_day_and_what_is_left(admin_client):
    from app.core.database import engine

    now = datetime.now(timezone.utc)
    async with engine.begin() as conn:
        for days_ago in (1, 2, 3):
            await _spend(conn, now - timedelta(days=days_ago), "extraction", "0.90", calls=200)
            await _spend(conn, now - timedelta(days=days_ago), "review", "0.10", calls=10)

    # No balance yet: spending shows, but nothing to count down from.
    body = (await admin_client.get("/api/v1/auth/admin/ai-credit")).json()
    assert body["balance"] is None and body["left"] is None and body["low"] is False
    assert body["per_day"] == 1.0
    yesterday = body["days"][-2]
    assert yesterday["total"] == 1.0
    assert [t["name"] for t in yesterday["tasks"]] == ["Reading new jobs", "Checking the writing"]

    # After topping up to $10: about ten days left, no warning.
    body = (await admin_client.post("/api/v1/auth/admin/ai-credit", json={"balance_usd": 10})).json()
    assert body["balance"]["amount"] == 10.0 and body["left"] == 10.0
    assert body["days_left"] == 10.0 and body["low"] is False and body["warning"] is None

    # Spend $8.50 more: under two days left, so the admin is warned.
    async with engine.begin() as conn:
        await _spend(conn, now, "tailoring", "8.50", calls=40)
    status = (await admin_client.get("/api/v1/auth/admin/ai-status")).json()
    assert status["low"] is True and status["paused"] is False
    assert status["message"].startswith("About $1.50 of AI credit is left, about 1 day at the current rate.")


async def test_topping_up_turns_ai_back_on_at_once(admin_client):
    from app.llm import client as llm_module

    llm_module.PAUSE_FILE.write_text(repr(time.time() + 1800))
    assert llm_module.credits_paused()
    status = (await admin_client.get("/api/v1/auth/admin/ai-status")).json()
    assert status["paused"] is True and "credits have run out" in status["message"]

    r = await admin_client.post("/api/v1/auth/admin/ai-credit", json={"balance_usd": 5})
    assert r.status_code == 200
    assert not llm_module.credits_paused()
    assert r.json()["paused"] is False

    assert (await admin_client.post("/api/v1/auth/admin/ai-credit", json={"balance_usd": -1})).status_code == 422


async def test_only_the_admin_sees_spending():
    from app.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/auth/admin/ai-credit")).status_code in (401, 403)
        assert (await client.post("/api/v1/auth/admin/ai-credit", json={"balance_usd": 5})).status_code in (401, 403)
