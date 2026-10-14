"""The message step after applying: the app finds the person to write to
and writes a short note the user sends from their own LinkedIn."""

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000a501")
JOB = uuid.UUID("00000000-0000-0000-0000-0000000a5001")
LINKEDIN_JOB = uuid.UUID("00000000-0000-0000-0000-0000000a5002")

NOTE = (
    "Hi Dana, I just applied for the Product Manager role at Stripe — I led the payments work at Acme "
    "that cut failed checkouts by a third. Would you be open to a short chat about the team? Ada"
)


class FakeLLM:
    def __init__(self, note=NOTE):
        self.note = note
        self.prompts: list[str] = []

    async def generate(self, task_type, system_prompt, user_prompt, **kwargs):
        self.prompts.append(user_prompt)
        return self.note


@pytest.fixture
async def client(monkeypatch):
    from app.api.deps import get_current_user_id
    from app.core.database import engine
    from app.main import app
    from app.services.outreach import contact_finder

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE outreach_logs, job_contacts, application_tracking, candidate_profiles, jobs, users CASCADE"
        ))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:id, 'ada@test.dev', 'Ada Obi', 'user')"
        ), {"id": USER})
        await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, home_country, links) VALUES (gen_random_uuid(), :u, 'NG', '{}'::jsonb)"
        ), {"u": USER})
        for job_id, url in ((JOB, "https://job-boards.greenhouse.io/stripe/jobs/301"),
                            (LINKEDIN_JOB, "https://www.linkedin.com/jobs/view/4012345678")):
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, status, job_url) VALUES (:id, 'Stripe', 'Product Manager', 'scored', :url)"
            ), {"id": job_id, "url": url})

    lookups: list[str] = []

    async def fake_lookup(*, company, role, location=None, max_searches=5):
        lookups.append(company)
        return {"name": "Dana Lee", "title": "Head of Product", "confidence": "high",
                "linkedin_url": "https://www.linkedin.com/in/danalee", "source_notes": "Leads product at Stripe."}

    monkeypatch.setattr(contact_finder, "find_contact_for_job", fake_lookup)
    llm = FakeLLM()
    monkeypatch.setattr("app.llm.client.llm_client", llm)

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        c.lookups, c.llm = lookups, llm
        yield c
    app.dependency_overrides.clear()


async def test_after_applying_the_app_finds_someone_and_writes_a_note(client):
    view = (await client.get(f"/api/v1/outreach/{JOB}")).json()
    assert view["can_message"] is False and view["auto"] is False
    r = await client.post(f"/api/v1/outreach/{JOB}/prepare")
    assert r.status_code == 409 and "Send the application first" in r.json()["detail"]

    await client.post(f"/api/v1/jobs/{JOB}/mark-applied")
    view = (await client.get(f"/api/v1/outreach/{JOB}")).json()
    # Sent today: the page writes it by itself.
    assert view["can_message"] is True and view["auto"] is True and view["status"] is None

    r = await client.post(f"/api/v1/outreach/{JOB}/prepare")
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["status"] == "drafted" and view["auto"] is False
    assert view["contact"]["name"] == "Dana Lee"
    assert view["contact"]["linkedin_url"] == "https://www.linkedin.com/in/danalee"
    # Plain English: the long dash the model wrote is gone.
    assert "—" not in view["message"] and view["message"].startswith("Hi Dana,")
    assert view["chars"] == len(view["message"]) and view["max_chars"] == 300
    prompt = client.llm.prompts[0]
    assert "Product Manager at Stripe" in prompt and "Dana Lee, Head of Product" in prompt
    assert "Never say or hint that an app" in prompt
    assert 'Start with "Hi"' in prompt and "Don't move a skill" in prompt

    # Opening the page again costs nothing: the note and the person are kept.
    again = (await client.post(f"/api/v1/outreach/{JOB}/prepare")).json()
    assert again["message"] == view["message"] and client.lookups == ["Stripe"]

    # Writing it again keeps the person: no new search.
    client.llm.note = "Hi Dana, I've just applied for the Product Manager role. Would you be open to a short chat? Ada"
    again = (await client.post(f"/api/v1/outreach/{JOB}/prepare", json={"rewrite": True})).json()
    assert again["message"] == client.llm.note and client.lookups == ["Stripe"]
    assert again["contact"]["name"] == "Dana Lee"

    # The user's edits are kept, without long dashes.
    r = await client.put(f"/api/v1/outreach/{JOB}", json={"message": "Hi Dana — I applied today. Ada"})
    assert "—" not in r.json()["message"]

    r = await client.put(f"/api/v1/outreach/{JOB}", json={"status": "sent"})
    assert r.json()["status"] == "sent" and r.json()["sent_at"]
    tracked = (await client.get("/api/v1/tracking")).json()
    assert tracked[0]["message"] == "sent"

    # Not sent after all.
    r = await client.put(f"/api/v1/outreach/{JOB}", json={"status": "drafted"})
    assert r.json()["status"] == "drafted" and r.json()["sent_at"] is None


async def test_the_note_is_checked_and_kept_short(client, monkeypatch):
    from app.services.outreach import message

    client.llm.note = "Hi Dana, I just applied for the Product Manager role. " + "I led payments at Acme. " * 14 + "Ada"
    asked: list[list[str]] = []

    async def finds_something(text, *, what, llm=None):
        return ['"leverage" is a word people don\'t say out loud.'] if not asked else []

    async def shortens(lines, problems, *, what, llm=None):
        asked.append(problems)
        return ["Hi Dana, I just applied for the Product Manager role and led payments at Acme. Open to a chat? Ada"]

    monkeypatch.setattr(message, "read_through", finds_something)
    monkeypatch.setattr(message, "revise_plainly", shortens)

    await client.post(f"/api/v1/jobs/{JOB}/mark-applied")
    view = (await client.post(f"/api/v1/outreach/{JOB}/prepare")).json()
    assert any("LinkedIn only allows 300" in p for p in asked[0])
    assert any("leverage" in p for p in asked[0])
    assert view["chars"] <= 300 and view["problems"] == []


async def test_when_no_one_is_found_the_note_is_still_written(client, monkeypatch):
    from app.services.outreach import contact_finder

    async def fails(**kwargs):
        raise RuntimeError("search failed")

    monkeypatch.setattr(contact_finder, "find_contact_for_job", fails)
    await client.post(f"/api/v1/jobs/{JOB}/mark-applied")
    view = (await client.post(f"/api/v1/outreach/{JOB}/prepare")).json()
    assert view["status"] == "drafted" and view["message"]
    assert view["contact"] is None
    assert view["people_search_url"] == "https://www.linkedin.com/search/results/people/?keywords=Stripe"


async def test_skipping_costs_nothing(client):
    await client.post(f"/api/v1/jobs/{JOB}/mark-applied")
    view = (await client.put(f"/api/v1/outreach/{JOB}", json={"status": "skipped"})).json()
    assert view["status"] == "skipped" and view["auto"] is False and view["message"] is None
    assert client.lookups == [] and client.llm.prompts == []


async def test_older_applications_wait_to_be_asked_and_linkedin_jobs_say_where_to_look(client):
    from app.core.database import engine

    await client.post(f"/api/v1/jobs/{LINKEDIN_JOB}/mark-applied")
    view = (await client.get(f"/api/v1/outreach/{LINKEDIN_JOB}")).json()
    assert view["linkedin_job_url"] == "https://www.linkedin.com/jobs/view/4012345678"

    async with engine.begin() as conn:
        await conn.execute(text("UPDATE application_tracking SET applied_at = :at"),
                           {"at": datetime.now(timezone.utc) - timedelta(days=10)})
    view = (await client.get(f"/api/v1/outreach/{LINKEDIN_JOB}")).json()
    assert view["can_message"] is True and view["auto"] is False
