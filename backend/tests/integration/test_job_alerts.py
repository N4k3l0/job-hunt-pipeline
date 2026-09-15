"""LinkedIn alert sync end to end: keys, reading emails once, reusing jobs
the app already has, per-user markers, Rate matches and the posting
lookup. The job board lookup is faked."""

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import Header
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DATABASE_URL
from tests.linkedin_alert_email import alert_email_html

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

USER = uuid.UUID("00000000-0000-0000-0000-00000000a501")
OTHER = uuid.UUID("00000000-0000-0000-0000-00000000a502")
EXISTING = uuid.UUID("50000000-0000-0000-0000-000000000001")


@pytest.fixture
async def client(monkeypatch):
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE job_alert_keys, job_alert_emails, job_alert_hits, linkedin_jobs, job_ratings, "
            "user_job_states, application_tracking, job_scores, candidate_skills, candidate_work_history, "
            "candidate_profiles, jobs, job_sources, users CASCADE"
        ))
        for user, email in ((USER, "alerts@test.dev"), (OTHER, "other@test.dev")):
            await conn.execute(text("INSERT INTO users (id, email, name, role) VALUES (:u, :e, 'A', 'user')"), {"u": user, "e": email})
            await conn.execute(text(
                "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference) "
                "VALUES (gen_random_uuid(), :u, ARRAY['Automation Engineer'], 'any')"
            ), {"u": user})
        # Globex's AI Engineer role in London, already found by another source.
        from app.services.parsing.normalizer import compute_canonical_hash
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, location, country, status, canonical_hash, raw_description, discovered_at) "
            "VALUES (:id, 'Globex', 'AI Engineer', 'London, UK', 'GB', 'expired', :h, :d, now())"
        ), {"id": EXISTING, "h": compute_canonical_hash("Globex", "AI Engineer", "London", "GB"), "d": "Build agents. " * 30})

    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


def _email(message_id: str, **kwargs) -> dict:
    return {"message_id": message_id, "received_at": datetime.now(timezone.utc).isoformat(), "html": alert_email_html(**kwargs)}


async def _send(client, key, *messages):
    return await client.post(
        "/api/v1/job-alerts/linkedin", json={"messages": list(messages)}, headers={"Authorization": f"Bearer {key}"},
    )


async def test_alert_emails_become_jobs(client, monkeypatch):
    from app.core.database import engine

    assert (await client.get("/api/v1/job-alerts/status")).json()["has_key"] is False
    key = (await client.post("/api/v1/job-alerts/key")).json()["key"]
    assert key.startswith("jha_")

    assert (await _send(client, "jha_wrong", _email("m1"))).status_code == 401
    assert (await client.post("/api/v1/job-alerts/linkedin", json={"messages": []})).status_code == 401

    r = await _send(client, key, _email("m1"))
    assert r.status_code == 200, r.text
    assert r.json() == {"emails_read": 1, "emails_already_read": 0, "jobs_found": 4, "jobs_added": 3}

    # The same email again changes nothing; a later email with the same jobs counts them again.
    assert (await _send(client, key, _email("m1"))).json()["emails_already_read"] == 1
    assert (await _send(client, key, _email("m2"))).json() == {
        "emails_read": 1, "emails_already_read": 0, "jobs_found": 4, "jobs_added": 0,
    }

    async with engine.connect() as conn:
        jobs = {row.external_id or row.company: row for row in (await conn.execute(text(
            "SELECT j.id, j.external_id, j.company, j.job_url, j.country, j.remote_type, j.salary_min, j.salary_currency, "
            "j.status, j.raw_content, h.times_sent, h.alert_search, h.position "
            "FROM job_alert_hits h JOIN jobs j ON j.id = h.job_id WHERE h.user_id = :u"
        ), {"u": USER})).all()}
        scored = (await conn.execute(text(
            "SELECT count(*) FROM job_scores s JOIN job_alert_hits h ON h.job_id = s.job_id AND h.user_id = s.user_id"
        ))).scalar()
    assert len(jobs) == 4 and scored == 4
    sunny = jobs["4100000002"]
    assert (sunny.job_url, sunny.country, sunny.remote_type, sunny.salary_min, sunny.salary_currency) == (
        "https://www.linkedin.com/jobs/view/4100000002", "US", "onsite", 74000, "USD",
    )
    assert (sunny.times_sent, sunny.alert_search, sunny.position) == (2, "Automation Engineer", 1)
    assert jobs["4100000003"].country == "CA"
    assert "otpToken" not in sunny.raw_content and "Test Person" not in sunny.raw_content
    # The job the app already had is reused, and reopened: LinkedIn still lists it.
    globex = jobs["Globex"]
    assert globex.id == EXISTING and globex.status == "scored"

    status = (await client.get("/api/v1/job-alerts/status")).json()
    assert (status["emails_read"], status["jobs_sent"]) == (2, 4)
    assert status["searches"] == [{"search": "Automation Engineer", "location": "United States", "jobs": 4}]

    # Marked for this user only.
    inbox = (await client.get("/api/v1/jobs", params={"min_score": 0})).json()["jobs"]
    assert inbox and all(j["linkedin_alert"] for j in inbox)
    detail = (await client.get(f"/api/v1/jobs/{sunny.id}")).json()
    assert detail["linkedin_alert"]["search"] == "Automation Engineer" and detail["linkedin_alert"]["times_sent"] == 2
    other = (await client.get(f"/api/v1/jobs/{sunny.id}", headers={"x-test-user": str(OTHER)})).json()
    assert other["linkedin_alert"] is None

    # Rate matches offers alert jobs whatever their score, and counts them apart.
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job_scores SET overall_fit = 10 WHERE user_id = :u"), {"u": USER})
    queue = (await client.get("/api/v1/ratings/queue")).json()["jobs"]
    assert {j["id"] for j in queue} == {str(row.id) for row in jobs.values()}
    await client.put(f"/api/v1/ratings/{sunny.id}", json={"rating": "good"})
    results = (await client.get("/api/v1/ratings/results")).json()
    assert results["linkedin_alerts"] == {"rated": 1, "good": 1, "others_rated": 0, "others_good": 0}

    # Postings from the companies' job boards, looked up once per job.
    from app.services.job_alerts import details

    looked_up = []

    async def fake_lookup(company, title):
        looked_up.append(company)
        if company == "Sunny Staffing":
            return "https://job-boards.greenhouse.io/sunny/jobs/123", "<p>" + "Automate workflows. " * 20 + "</p>"
        return None, None

    monkeypatch.setattr(details, "_lookup", fake_lookup)
    r = await client.get("/api/v1/cron/job-alert-details", headers={"Authorization": "Bearer test-cron-secret"})
    assert r.json()["checked"] == 3 and r.json()["descriptions_found"] == 1, r.json()
    assert sorted(looked_up) == ["Acme Talent", "Northwind", "Sunny Staffing"]  # Globex already had a description
    again = await client.get("/api/v1/cron/job-alert-details", headers={"Authorization": "Bearer test-cron-secret"})
    assert again.json()["checked"] == 0
    async with engine.connect() as conn:
        apply_url, description = (await conn.execute(
            text("SELECT apply_url, raw_description FROM jobs WHERE id = :id"), {"id": sunny.id}
        )).one()
    assert apply_url == "https://job-boards.greenhouse.io/sunny/jobs/123" and "Automate workflows" in description

    # A deleted key stops working.
    assert (await client.delete("/api/v1/job-alerts/key")).status_code == 204
    assert (await _send(client, key, _email("m3"))).status_code == 401
