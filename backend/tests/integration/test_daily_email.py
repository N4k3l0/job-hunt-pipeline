"""The daily email: what goes in it, once a day per user, opting out, and
nothing sent until email is set up. The email service is faked."""

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

ADA = uuid.UUID("00000000-0000-0000-0000-00000000c701")
BEN = uuid.UUID("00000000-0000-0000-0000-00000000c702")
NOW = datetime.now(timezone.utc)


async def _job(conn, title, company, score, *, user=ADA, days_old=0.5, status="scored"):
    job_id = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO jobs (id, company, title, location, remote_type, status, discovered_at) "
        "VALUES (:id, :c, :t, 'Remote', 'full_remote', :s, :d)"
    ), {"id": job_id, "c": company, "t": title, "s": status, "d": NOW - timedelta(days=days_old)})
    await conn.execute(text(
        "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, seniority_score, "
        "industry_score, geo_score, remote_score, salary_score, visa_score, overall_fit, priority, score_version) "
        "VALUES (gen_random_uuid(), :j, :u, 'general', 20, 5, 0, 0, 0, 0, 0, 0, :fit, 'medium', 2)"
    ), {"j": job_id, "u": user, "fit": score})
    return job_id


@pytest.fixture
async def setup(monkeypatch):
    from app.main import app
    from app.api.deps import get_current_user, get_current_user_id
    from app.core.database import engine
    from app.models.user import User
    from app.services.notifications import digest, email

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE auto_applications, application_tracking, tailored_applications, user_job_states, job_scores, "
            "candidate_skills, candidate_profiles, jobs, users CASCADE"
        ))
        for user, name in ((ADA, "Ada Lovelace"), (BEN, "Ben")):
            await conn.execute(text("INSERT INTO users (id, email, name, role) VALUES (:u, :e, :n, 'user')"),
                               {"u": user, "e": f"{name.split()[0].lower()}@test.dev", "n": name})
            await conn.execute(text(
                "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference) "
                "VALUES (gen_random_uuid(), :u, ARRAY['Engineer'], 'any')"
            ), {"u": user})
        ids = {
            "best": await _job(conn, "Staff Engineer", "Acme", 88),
            "good": await _job(conn, "AI Engineer", "Globex", 72),
            "same_job_elsewhere": await _job(conn, "AI Engineer", "Globex", 70),
            "low": await _job(conn, "Engineer, Billing", "Initech", 30),
            "old": await _job(conn, "Platform Engineer", "Umbrella", 90, days_old=5),
            "dismissed": await _job(conn, "Data Engineer", "Hooli", 80),
            "applied": await _job(conn, "Backend Engineer", "Pied Piper", 85),
        }
        await conn.execute(text("INSERT INTO user_job_states (id, user_id, job_id, status) VALUES (gen_random_uuid(), :u, :j, 'dismissed')"),
                           {"u": ADA, "j": ids["dismissed"]})
        await conn.execute(text("INSERT INTO application_tracking (id, user_id, job_id, status) VALUES (gen_random_uuid(), :u, :j, 'applied')"),
                           {"u": ADA, "j": ids["applied"]})
        await conn.execute(text(
            "INSERT INTO application_tracking (id, user_id, job_id, status, follow_up_date) "
            "VALUES (gen_random_uuid(), :u, :j, 'applied', current_date - 1)"
        ), {"u": ADA, "j": ids["old"]})
        await conn.execute(text(
            "INSERT INTO auto_applications (id, user_id, job_id, status, form, answers) "
            "VALUES (gen_random_uuid(), :u, :j, 'needs_you', CAST(:form AS jsonb), '{}'::jsonb)"
        ), {"u": ADA, "j": ids["best"], "form": '[{"key": "why", "label": "Why us?", "type": "textarea", "required": true, "kind": "question"}]'})

    sent: list[dict] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)

    configured = {"on": True}
    monkeypatch.setattr(digest, "send_email", fake_send)
    monkeypatch.setattr(digest, "email_configured", lambda: configured["on"])
    monkeypatch.setattr(digest, "frontend_url", lambda: "https://app.example")
    monkeypatch.setattr(digest, "api_public_url", lambda: "https://api.example")
    monkeypatch.setattr(email, "email_configured", lambda: configured["on"])
    from app.api.v1 import notifications
    monkeypatch.setattr(notifications, "send_email", fake_send)
    monkeypatch.setattr(notifications, "email_configured", lambda: configured["on"])
    monkeypatch.setattr(notifications, "frontend_url", lambda: "https://app.example")

    async def fake_user(x_test_user: str = Header()):
        async with engine.connect() as conn:
            row = (await conn.execute(text("SELECT id FROM users WHERE id = :u"), {"u": x_test_user})).scalar()
        from app.core.database import create_worker_session
        async with create_worker_session()() as db:
            return await db.get(User, row)

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user] = fake_user
    app.dependency_overrides[get_current_user_id] = fake_user_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-test-user": str(ADA)},
    ) as client:
        yield {"client": client, "sent": sent, "ids": ids, "configured": configured}
    app.dependency_overrides.clear()


async def test_daily_email_content_and_schedule(setup):
    from app.services.notifications.digest import send_due_digests

    sent = setup["sent"]
    morning = NOW.replace(hour=7, minute=5, second=0, microsecond=0)
    if morning > NOW:
        morning -= timedelta(days=1)

    # Before the send hour: nothing.
    assert (await send_due_digests(morning.replace(hour=6)))["status"] == "not yet"
    assert sent == []

    outcome = await send_due_digests(morning + timedelta(hours=1))
    assert outcome["sent"] == 1 and outcome["nothing_new"] == 1, outcome  # Ben has nothing
    email = sent[0]
    assert email["to"] == "ada@test.dev"
    # Two new matches (one posting per job), one application waiting, one follow-up.
    assert email["subject"] == "2 new job matches, 1 application needs you, 1 follow-up due"
    assert "Good morning, Ada." in email["html"]
    ids = setup["ids"]
    assert str(ids["best"]) in email["html"] and "Globex" in email["html"]
    for left_out in ("low", "old", "dismissed", "applied"):
        assert f"/dashboard/jobs/{ids[left_out]}" not in email["html"], left_out
    assert "1 question to answer" in email["html"]
    assert "Follow up on" in email["html"]
    assert email["unsubscribe_url"].startswith("https://api.example/api/v1/notifications/unsubscribe?u=")

    # Once a day.
    assert (await send_due_digests(morning + timedelta(hours=3)))["sent"] == 0
    assert len(sent) == 1

    # Nothing while email isn't set up.
    setup["configured"]["on"] = False
    assert (await send_due_digests(morning + timedelta(days=1, hours=1)))["status"] == "email not set up"


async def test_settings_preview_test_send_and_unsubscribe(setup, monkeypatch):
    client, sent = setup["client"], setup["sent"]

    settings = (await client.get("/api/v1/notifications/settings")).json()
    assert settings == {"daily_email": True, "email": "ada@test.dev", "email_configured": True, "last_sent_at": None}

    preview = (await client.get("/api/v1/notifications/digest/preview")).json()
    assert preview["empty"] is False and preview["subject"].startswith("2 new job matches")
    assert sent == []  # a preview sends nothing

    r = await client.post("/api/v1/notifications/digest/test")
    assert r.status_code == 200 and sent[-1]["subject"].startswith("[Test] ")
    setup["configured"]["on"] = False
    r = await client.post("/api/v1/notifications/digest/test")
    assert r.status_code == 503 and "isn't set up" in r.json()["detail"]
    setup["configured"]["on"] = True

    r = await client.put("/api/v1/notifications/settings", json={"daily_email": False})
    assert r.json()["daily_email"] is False
    await client.put("/api/v1/notifications/settings", json={"daily_email": True})

    from app.services.notifications.digest import unsubscribe_token
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "test-secret")
    bad = await client.get("/api/v1/notifications/unsubscribe", params={"u": str(ADA), "t": "nope"}, headers={})
    assert "doesn't work" in bad.text
    good = await client.get("/api/v1/notifications/unsubscribe", params={"u": str(ADA), "t": unsubscribe_token(ADA)}, headers={})
    assert good.status_code == 200 and "won't get daily emails" in good.text
    assert (await client.get("/api/v1/notifications/settings")).json()["daily_email"] is False

    from app.services.notifications.digest import send_due_digests
    assert (await send_due_digests(NOW.replace(hour=23, minute=0)))["sent"] == 0
