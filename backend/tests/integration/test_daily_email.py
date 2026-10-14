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


async def _job(conn, title, company, score, *, user=ADA, days_old=0.5, status="scored", described=True):
    job_id = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO jobs (id, company, title, location, remote_type, status, discovered_at, raw_description) "
        "VALUES (:id, :c, :t, 'Remote', 'full_remote', :s, :d, :desc)"
    ), {"id": job_id, "c": company, "t": title, "s": status, "d": NOW - timedelta(days=days_old),
        "desc": ("What you'll do: build things with a small team. " * 12) if described else None})
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
        for user, name, role in ((ADA, "Ada Lovelace", "admin"), (BEN, "Ben", "user")):
            await conn.execute(text("INSERT INTO users (id, email, name, role) VALUES (:u, :e, :n, :r)"),
                               {"u": user, "e": f"{name.split()[0].lower()}@test.dev", "n": name, "r": role})
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
            # A LinkedIn alert job known only by its title: listed after the read ones.
            "title_only": await _job(conn, "Automation Engineer", "Arla Foods", 95, described=False),
            "stale_follow_up": await _job(conn, "Site Engineer", "Wonka", 20, days_old=120),
        }
        await conn.execute(text("INSERT INTO user_job_states (id, user_id, job_id, status) VALUES (gen_random_uuid(), :u, :j, 'dismissed')"),
                           {"u": ADA, "j": ids["dismissed"]})
        await conn.execute(text("INSERT INTO application_tracking (id, user_id, job_id, status) VALUES (gen_random_uuid(), :u, :j, 'applied')"),
                           {"u": ADA, "j": ids["applied"]})
        await conn.execute(text(
            "INSERT INTO application_tracking (id, user_id, job_id, status, follow_up_date) "
            "VALUES (gen_random_uuid(), :u, :j, 'applied', current_date - 1)"
        ), {"u": ADA, "j": ids["old"]})
        # A follow-up a month overdue: the moment has passed.
        await conn.execute(text(
            "INSERT INTO application_tracking (id, user_id, job_id, status, follow_up_date) "
            "VALUES (gen_random_uuid(), :u, :j, 'applied', current_date - 30)"
        ), {"u": ADA, "j": ids["stale_follow_up"]})
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
    assert (await send_due_digests(morning.replace(hour=6)))["status"] == "nobody due"
    assert sent == []

    outcome = await send_due_digests(morning + timedelta(hours=1))
    # Only Ada, who runs the app, until it's on for everyone.
    assert outcome["sent"] == 1 and outcome["nothing_new"] == 0, outcome
    email = sent[0]
    assert email["to"] == "ada@test.dev"
    # Three new matches (one posting per job), one application waiting, one follow-up.
    assert email["subject"] == "3 new job matches, 1 application needs you, 1 follow-up due"
    assert "Good morning, Ada." in email["html"]
    ids = setup["ids"]
    assert str(ids["best"]) in email["html"] and "Globex" in email["html"]
    for left_out in ("low", "old", "dismissed", "applied"):
        assert f'/dashboard/jobs/{ids[left_out]}"' not in email["html"], left_out
    # The follow-up goes straight to the message step on its job page.
    assert f'/dashboard/jobs/{ids["old"]}#message"' in email["html"]
    # Jobs the app has read come first; a title-only one only after them.
    assert email["html"].index(str(ids["best"])) < email["html"].index(str(ids["title_only"]))
    assert "1 question to answer" in email["html"]
    assert email["html"].count("Follow up on") == 1 and "Wonka" not in email["html"]
    # Plain English: no long dashes anywhere in it.
    assert "\u2014" not in email["html"] and "\u2014" not in email["text"] and "\u2014" not in email["subject"]
    assert email["unsubscribe_url"].startswith("https://api.example/api/v1/notifications/unsubscribe?u=")

    # Once a day.
    assert (await send_due_digests(morning + timedelta(hours=3)))["sent"] == 0
    assert len(sent) == 1

    # Turned on for everyone: Ben is considered too (he has nothing new).
    from app.core.database import engine
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE users SET preferences = '{\"digest_everyone\": true}'::jsonb WHERE id = :u"), {"u": ADA})
    assert (await send_due_digests(morning + timedelta(hours=4)))["nothing_new"] == 1

    # No email service: the admin's Gmail script sends them instead.
    setup["configured"]["on"] = False
    assert (await send_due_digests(morning + timedelta(days=1, hours=1)))["status"].startswith("no email service")


async def test_settings_preview_test_send_and_unsubscribe(setup, monkeypatch):
    client, sent = setup["client"], setup["sent"]

    settings = (await client.get("/api/v1/notifications/settings")).json()
    assert settings == {"daily_email": True, "email": "ada@test.dev", "email_configured": True, "last_sent_at": None,
                        "sends_from": None, "test_waiting": False, "everyone": False}

    preview = (await client.get("/api/v1/notifications/digest/preview")).json()
    assert preview["empty"] is False and preview["subject"].startswith("3 new job matches")
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


async def test_the_gmail_script_sends_them_to_the_admin_first(setup):
    """No email service: the admin's alert script collects the day's emails
    and test emails, sends them from its Gmail, and says which went."""
    from app.core.database import engine
    from app.services.notifications.outbox import due_emails, mark_sent

    client = setup["client"]
    setup["configured"]["on"] = False
    morning = NOW.replace(hour=8, minute=0, second=0, microsecond=0)
    if morning > NOW:
        morning -= timedelta(days=1)

    # Before an admin's script reads an inbox, nothing can send.
    assert (await client.post("/api/v1/notifications/digest/test")).status_code == 503
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE users SET preferences = '{\"alert_inbox\": \"alerts@gmail.com\"}'::jsonb WHERE id = :u"), {"u": ADA})
    settings = (await client.get("/api/v1/notifications/settings")).json()
    assert settings["email_configured"] is True and settings["sends_from"] == "alerts@gmail.com"

    # A test waits for the script's next run.
    r = await client.post("/api/v1/notifications/digest/test")
    assert r.json() == {"sent_to": "ada@test.dev", "queued": True}
    assert (await client.get("/api/v1/notifications/settings")).json()["test_waiting"] is True

    from app.core.database import async_session
    async with async_session() as db:
        emails = await due_emails(db, now=morning)
    assert [e["id"].split(":")[0] for e in emails] == ["test", "digest"]  # Ben isn't an admin
    assert emails[0]["subject"].startswith("[Test] ") and emails[1]["to"] == "ada@test.dev"
    async with async_session() as db:
        assert await mark_sent(db, [e["id"] for e in emails], now=morning) == 2
    async with async_session() as db:
        assert await due_emails(db, now=morning) == []  # once a day, and the test went
    assert (await client.get("/api/v1/notifications/settings")).json()["test_waiting"] is False

    # Only an admin can turn it on for everyone.
    r = await client.put("/api/v1/notifications/settings", json={"everyone": True}, headers={"x-test-user": str(BEN)})
    assert r.status_code == 403
    r = await client.put("/api/v1/notifications/settings", json={"everyone": True})
    assert r.json()["everyone"] is True
