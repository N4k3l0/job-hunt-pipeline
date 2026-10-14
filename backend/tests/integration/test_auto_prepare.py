"""The app prepares applications by itself: the user's best new matches on
forms it can fill in (one per company, within their daily number), and
"Apply for me" pressed while the AI was paused, once it's back."""

import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

ME = uuid.UUID("00000000-0000-0000-0000-00000000e001")
OTHER = uuid.UUID("00000000-0000-0000-0000-00000000e002")


def job_id(n: int) -> uuid.UUID:
    return uuid.UUID(f"50000000-0000-0000-0000-{n:012d}")


LEVER = "https://jobs.lever.co/beta/11111111-2222-3333-4444-555555555555"
ASHBY = "https://jobs.ashbyhq.com/gamma/11111111-2222-3333-4444-555555555555"
# (number, company, title, apply url, score, days since last listed, status)
JOBS = [
    (1, "Acme", "Product Manager", "https://job-boards.greenhouse.io/acme/jobs/1", 90, 0, "enriched"),
    (2, "Acme", "Senior Product Manager", "https://job-boards.greenhouse.io/acme/jobs/2", 85, 0, "enriched"),
    (3, "Beta", "Product Manager, Growth", LEVER, 80, 1, "enriched"),
    (4, "Gamma", "Product Manager, Payments", ASHBY, 60, 0, "enriched"),
    (5, "Delta", "Product Manager, Data", "https://delta.wd1.myworkdayjobs.com/jobs/5", 95, 0, "enriched"),
    (6, "Epsilon", "Product Manager, Ops", "https://job-boards.greenhouse.io/epsilon/jobs/6", 95, 10, "enriched"),
    (7, "Zeta", "Product Manager, Mobile", "https://job-boards.greenhouse.io/zeta/jobs/7", 88, 0, "enriched"),
    (8, "Eta", "Product Manager, Web", "https://job-boards.greenhouse.io/eta/jobs/8", 87, 0, "enriched"),
    (9, "Theta", "Product Manager, AI", "https://job-boards.greenhouse.io/theta/jobs/9", 86, 0, "expired"),
]


async def _seed(conn, *, per_day: int):
    now = datetime.now(timezone.utc)
    await conn.execute(text(
        "TRUNCATE ai_credit_balances, ai_usage_hours, auto_applications, user_job_states, application_tracking, "
        "job_scores, candidate_profiles, jobs, users CASCADE"
    ))
    await conn.execute(text(
        "INSERT INTO users (id, email, name, role, preferences) VALUES "
        "(:me, 'me@test.dev', 'Me', 'user', CAST(:prefs AS jsonb)), (:other, 'other@test.dev', 'Other', 'user', '{}')"
    ), {"me": ME, "other": OTHER, "prefs": f'{{"auto_prepare_per_day": {per_day}}}'})
    for user in (ME, OTHER):
        await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, target_roles, home_country, remote_preference) "
            "VALUES (gen_random_uuid(), :user, ARRAY['Product Manager'], 'NG', 'any')"
        ), {"user": user})
    for n, company, title, url, score, unseen_days, status in JOBS:
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, apply_url, job_url, status, discovered_at, last_seen_at) "
            "VALUES (:id, :company, :title, :url, :url, :status, :found, :seen)"
        ), {"id": job_id(n), "company": company, "title": title, "url": url, "status": status,
            "found": now - timedelta(days=max(unseen_days, 2) + 3), "seen": now - timedelta(days=unseen_days)})
        for user in (ME, OTHER):
            await conn.execute(text(
                "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, "
                "seniority_score, industry_score, geo_score, remote_score, salary_score, visa_score, "
                "overall_fit, priority, score_version) "
                "VALUES (gen_random_uuid(), :job, :user, 'general', 1, 1, 0, 0, 0, 0, 0, 0, :score, 'high', 5)"
            ), {"job": job_id(n), "user": user, "score": score})
    await conn.execute(text(
        "INSERT INTO user_job_states (id, user_id, job_id, status) VALUES (gen_random_uuid(), :me, :job, 'dismissed')"
    ), {"me": ME, "job": job_id(7)})
    await conn.execute(text(
        "INSERT INTO auto_applications (id, user_id, job_id, status, answers) "
        "VALUES (gen_random_uuid(), :me, :job, 'needs_you', '{}')"
    ), {"me": ME, "job": job_id(8)})


@pytest.fixture
async def seeded():
    from app.core.database import engine

    async def seed(per_day: int = 2):
        async with engine.begin() as conn:
            await _seed(conn, per_day=per_day)
    return seed


def fake_preparer(calls: list):
    """Stands in for prepare_application: makes the application, as it
    would, without reading forms or asking the model."""
    from sqlalchemy import select

    from app.models.auto_apply import AutoApplication

    async def prepare(db, user_id, job, *, tailor, prepared_by=None):
        calls.append((user_id, job, prepared_by))
        application = (await db.execute(
            select(AutoApplication).where(AutoApplication.user_id == user_id, AutoApplication.job_id == job)
        )).scalar_one_or_none()
        if application is None:
            application = AutoApplication(user_id=user_id, job_id=job, answers={},
                                          result={"prepared_by": prepared_by} if prepared_by else None)
            db.add(application)
        application.status = "needs_you"
        application.error = None
        await db.commit()
        return application
    return prepare


async def test_picks_the_best_new_matches_it_can_fill_in(seeded):
    from app.core.database import async_session
    from app.services.auto_apply.auto_prepare import pick_jobs_to_prepare

    await seeded()
    async with async_session() as db:
        picked = await pick_jobs_to_prepare(db, ME, limit=5)
    # Acme's second job waits (one per company); below 70, not on a form
    # the app fills in, not listed for 10 days, dismissed, already
    # prepared and closed jobs are all left out.
    assert picked == [job_id(1), job_id(3)]


async def test_prepares_up_to_the_users_number_a_day(seeded):
    from app.core.database import async_session
    from app.services.auto_apply.auto_prepare import run

    await seeded(per_day=1)
    calls = []
    outcome = await run(limit=3, preparer=fake_preparer(calls), session_factory=async_session)
    assert outcome["prepared"] == 1 and outcome["failed"] == 0
    assert calls == [(ME, job_id(1), "app")]  # the other user didn't turn it on

    # The day's number is used up: the next run leaves the rest for tomorrow.
    outcome = await run(limit=3, preparer=fake_preparer(calls), session_factory=async_session)
    assert outcome["prepared"] == 0 and len(calls) == 1
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    outcome = await run(limit=3, preparer=fake_preparer(calls), session_factory=async_session, now=tomorrow)
    assert calls[-1] == (ME, job_id(3), "app")


async def test_nothing_while_the_ai_is_paused_and_waiting_ones_come_first(seeded):
    from app.core.database import async_session, engine
    from app.llm import client as llm_module
    from app.services.auto_apply.auto_prepare import run

    await seeded(per_day=2)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO auto_applications (id, user_id, job_id, status, answers, updated_at) "
            "VALUES (gen_random_uuid(), :other, :job, 'preparing', '{}', now() - interval '20 minutes')"
        ), {"other": OTHER, "job": job_id(4)})

    calls = []
    llm_module.PAUSE_FILE.write_text(repr(time.time() + 1800))
    outcome = await run(limit=3, preparer=fake_preparer(calls), session_factory=async_session)
    assert outcome["paused"] is True and calls == []

    llm_module.end_credits_pause()
    outcome = await run(limit=2, preparer=fake_preparer(calls), session_factory=async_session)
    assert calls[0] == (OTHER, job_id(4), None)  # the one that waited, first
    assert outcome["finished"] == 1 and outcome["prepared"] == 1


async def test_automatic_preparing_stops_when_the_credit_is_nearly_gone(seeded):
    from app.core.database import async_session, engine
    from app.services.auto_apply.auto_prepare import run

    await seeded(per_day=2)
    async with engine.begin() as conn:
        # $14.70 of the $15 budget used this month: under the $0.50 kept back.
        await conn.execute(text(
            "INSERT INTO ai_usage_hours (hour, task, model, calls, input_tokens, output_tokens, web_searches, cost_usd) "
            "VALUES (date_trunc('hour', now()), 'extraction', 'claude-haiku-4-5', 1, 0, 0, 0, 14.70)"
        ))
    calls = []
    outcome = await run(limit=3, preparer=fake_preparer(calls), session_factory=async_session)
    assert outcome["low_credit"] is True and calls == []


async def test_the_daily_number_is_the_users_to_set(seeded):
    from app.api.deps import DbSession, get_current_user
    from app.main import app
    from app.models.user import User

    await seeded(per_day=0)

    async def me(db: DbSession) -> User:
        return await db.get(User, ME)

    app.dependency_overrides[get_current_user] = me
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            body = (await client.get("/api/v1/auto-apply/settings")).json()
            assert body["per_day"] == 0 and body["choices"] == [0, 1, 2, 3, 5]
            body = (await client.put("/api/v1/auto-apply/settings", json={"per_day": 3})).json()
            assert body["per_day"] == 3
            assert (await client.get("/api/v1/auto-apply/settings")).json()["per_day"] == 3
            assert (await client.put("/api/v1/auto-apply/settings", json={"per_day": 50})).status_code == 422
    finally:
        app.dependency_overrides.clear()


async def _as_me():
    from fastapi import Header

    from app.api.deps import get_current_user_id
    from app.main import app

    async def me(x_test_user: str = Header(default=str(ME))) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = me
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_the_applications_page_lists_both_kinds_of_job(seeded):
    """One list to apply from: forms the app fills in, to tick and prepare
    together, and jobs on other sites, to open and mark applied."""
    from app.core.database import engine
    from app.main import app

    await seeded()
    async with engine.begin() as conn:
        # The same job posted twice shows once.
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, apply_url, job_url, status, discovered_at, last_seen_at) "
            "VALUES (:id, 'Acme', 'Product Manager', :url, :url, 'enriched', now() - interval '3 days', now())"
        ), {"id": job_id(20), "url": "https://job-boards.greenhouse.io/acme/jobs/20"})
        await conn.execute(text(
            "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, seniority_score, "
            "industry_score, geo_score, remote_score, salary_score, visa_score, overall_fit, priority, score_version) "
            "VALUES (gen_random_uuid(), :job, :me, 'general', 1, 1, 0, 0, 0, 0, 0, 0, 75, 'high', 5)"
        ), {"job": job_id(20), "me": ME})

    try:
        async with await _as_me() as client:
            r = await client.get("/api/v1/auto-apply/picks")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    body = r.json()
    # Best first. Unlike the app's own daily picks, the user may take two
    # from one company. Below 70, not listed for 10 days, dismissed,
    # already started and closed jobs are left out.
    assert [item["job_id"] for item in body["fill"]] == [str(job_id(n)) for n in (1, 2, 3)]
    assert [item["job_id"] for item in body["elsewhere"]] == [str(job_id(5))]
    first = body["fill"][0]
    assert (first["company"], first["title"], first["score"]) == ("Acme", "Product Manager", 90)
    assert body["elsewhere"][0]["url"] == "https://delta.wd1.myworkdayjobs.com/jobs/5"
    assert body["max_batch"] == 25 and body["cost_each_usd"] == 0.15


async def test_a_batch_is_prepared_a_few_at_a_time(seeded):
    from sqlalchemy import select

    from app.core.database import async_session
    from app.main import app
    from app.models.auto_apply import AutoApplication
    from app.services.auto_apply import batch
    from app.services.auto_apply.prepare import QUEUED

    await seeded(per_day=0)
    calls: list = []
    started: list = []

    async def record(user_id, job_ids):
        started.append(job_ids)

    original = batch.prepare_queued
    batch.prepare_queued = record
    try:
        async with await _as_me() as client:
            r = await client.post("/api/v1/auto-apply/batch", json={"job_ids": [
                str(job_id(1)), str(job_id(3)), str(job_id(8)), str(uuid.uuid4()),
            ]})
    finally:
        batch.prepare_queued = original
        app.dependency_overrides.clear()
    # Job 8 already has an application, and one job doesn't exist.
    assert r.status_code == 200, r.text
    assert r.json() == {"queued": 2, "skipped": 2}
    assert started == [[job_id(1), job_id(3)]]

    async with async_session() as db:
        rows = {a.job_id: a for a in (await db.execute(select(AutoApplication).where(AutoApplication.user_id == ME))).scalars()}
        assert (rows[job_id(1)].status, rows[job_id(1)].error) == ("preparing", QUEUED)
        # Stopped while it waited its turn: it stays stopped.
        rows[job_id(3)].status = "cancelled"
        await db.commit()

    outcome = await batch.prepare_queued(ME, started[0], preparer=fake_preparer(calls), session_factory=async_session)
    assert outcome == {"prepared": 1, "failed": 0}
    assert [job for _user, job, _by in calls] == [job_id(1)]


async def test_the_scheduler_leaves_a_batch_alone_while_it_runs(seeded):
    from app.core.database import async_session, engine
    from app.services.auto_apply.auto_prepare import run
    from app.services.auto_apply.prepare import QUEUED

    await seeded(per_day=0)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO auto_applications (id, user_id, job_id, status, answers, error) "
            "VALUES (gen_random_uuid(), :me, :job, 'preparing', '{}', :queued)"
        ), {"me": ME, "job": job_id(1), "queued": QUEUED})
    calls: list = []
    now = datetime.now(timezone.utc)
    soon = await run(limit=3, now=now + timedelta(minutes=20), preparer=fake_preparer(calls), session_factory=async_session)
    assert soon["finished"] == 0 and calls == []
    # Left behind (the server restarted): the scheduler finishes it.
    later = await run(limit=3, now=now + timedelta(minutes=50), preparer=fake_preparer(calls), session_factory=async_session)
    assert later["finished"] == 1 and [job for _user, job, _by in calls] == [job_id(1)]
