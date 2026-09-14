"""Step 2 end to end against Postgres: enrichment writes job facts and
rescoring, hard filters hide jobs per user, and top-match reviews respect
the daily cap. The extraction model and deep review are faked."""

import json
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

NIGERIA_USER = uuid.UUID("00000000-0000-0000-0000-00000000c001")
US_USER = uuid.UUID("00000000-0000-0000-0000-00000000c002")

US_ONLY = uuid.UUID("40000000-0000-0000-0000-000000000001")
SHORT = uuid.UUID("40000000-0000-0000-0000-000000000002")
OLD = uuid.UUID("40000000-0000-0000-0000-000000000003")
UK_NO_SPONSOR = uuid.UUID("40000000-0000-0000-0000-000000000004")
LOW_SALARY = uuid.UUID("40000000-0000-0000-0000-000000000005")

LONG_DESCRIPTION = "You will own the product roadmap and work with engineering. " * 10


async def _seed(conn):
    await conn.execute(text(
        "TRUNCATE user_job_states, application_tracking, job_scores, candidate_profiles, "
        "invite_requests, jobs, users CASCADE"
    ))
    await conn.execute(text(
        "INSERT INTO users (id, email, name, role) VALUES "
        "(:ng, 'ng@test.dev', 'NG', 'user'), (:us, 'us@test.dev', 'US', 'user')"
    ), {"ng": NIGERIA_USER, "us": US_USER})
    await conn.execute(text(
        "INSERT INTO candidate_profiles (id, user_id, target_roles, home_country, visa_statuses, "
        "salary_min, salary_currency, remote_preference) VALUES "
        "(gen_random_uuid(), :ng, ARRAY['Product Manager'], 'NG', NULL, NULL, 'USD', 'any'), "
        "(gen_random_uuid(), :us, ARRAY['Product Manager'], 'US', CAST(:visa AS jsonb), 100000, 'USD', 'any')"
    ), {"ng": NIGERIA_USER, "us": US_USER, "visa": json.dumps({"GB": "need_sponsorship"})})

    now = datetime.now(timezone.utc)
    # Distinct titles: the inbox shows postings with the same company and
    # title once.
    jobs = [
        (US_ONLY, "Product Manager", None, "full_remote", LONG_DESCRIPTION, now, None, None),
        (SHORT, "Senior Product Manager", None, "full_remote", "Short.", now, None, None),
        (OLD, "Product Manager, Growth", None, "full_remote", LONG_DESCRIPTION, now - timedelta(days=60), None, None),
        (UK_NO_SPONSOR, "Product Manager, London", "GB", "onsite", "Short.", now, None, None),
        (LOW_SALARY, "Product Manager, Payments", None, "full_remote", "Short.", now, 60000, "USD"),
    ]
    for job_id, title, country, remote, desc, discovered, salary_max, currency in jobs:
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, country, remote_type, raw_description, status, "
            "discovered_at, salary_max, salary_currency, salary_text) VALUES "
            "(:id, 'Acme', :title, :country, :remote, :desc, 'enriched', :discovered, :salary_max, :currency, :salary_text)"
        ), {"id": job_id, "title": title, "country": country, "remote": remote, "desc": desc,
            "discovered": discovered, "salary_max": salary_max, "currency": currency,
            "salary_text": f"Up to ${salary_max:,}" if salary_max else None})
    await conn.execute(text(
        "INSERT INTO job_entities (id, job_id, skills, requirements, keywords, sponsorship_available, enriched_at) "
        "VALUES (gen_random_uuid(), :uk, '[]', '[]', '[]', false, now()), "
        "(gen_random_uuid(), :low, '[]', '[]', '[]', NULL, now())"
    ), {"uk": UK_NO_SPONSOR, "low": LOW_SALARY})


@pytest.fixture
async def client(monkeypatch):
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine
    from app.services.enrichment import job_enricher

    async with engine.begin() as conn:
        await _seed(conn)

    extracted_calls = []

    async def fake_extract(job):
        extracted_calls.append(job.id)
        return {
            "required_skills": ["Roadmapping", "SQL"],
            "nice_to_have_skills": [],
            "requirements": ["Own the roadmap"],
            "keywords": ["B2B SaaS"],
            "seniority": "mid",
            "eligible_countries": ["US"],
            "sponsorship_available": False,
        }

    monkeypatch.setattr(job_enricher, "extract_job_details", fake_extract)
    monkeypatch.setenv("CRON_SECRET", "test-cron-secret")

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test",
        headers={"Authorization": "Bearer test-cron-secret"},
    ) as c:
        c.extracted_calls = extracted_calls
        for user in (NIGERIA_USER, US_USER):
            r = await c.post("/api/v1/candidates/rescore", headers={"x-test-user": str(user)})
            assert r.status_code == 200, r.text
        yield c
    app.dependency_overrides.clear()


async def _inbox(client, user) -> set[str]:
    r = await client.get("/api/v1/jobs", params={"min_score": 0}, headers={"x-test-user": str(user)})
    assert r.status_code == 200, r.text
    return {j["id"] for j in r.json()["jobs"]}


async def test_enrich_endpoint_reads_recent_jobs_and_rescores(client):
    from app.core.database import engine

    r = await client.get("/api/v1/cron/enrich", params={"limit": 10})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enriched"] == 1
    assert body["skipped_short"] == 1
    assert body["failed"] == 0
    assert body["pending"] == 0
    assert client.extracted_calls == [US_ONLY]
    assert body["scores_updated"] == 2  # one job x two users

    async with engine.connect() as conn:
        entity = (await conn.execute(text(
            "SELECT e.skills, e.eligible_countries, e.enriched_at IS NOT NULL, j.seniority "
            "FROM job_entities e JOIN jobs j ON j.id = e.job_id WHERE e.job_id = :id"
        ), {"id": US_ONLY})).one()
        short_enriched = (await conn.execute(text(
            "SELECT enriched_at IS NOT NULL FROM job_entities WHERE job_id = :id"
        ), {"id": SHORT})).scalar()
        old_entity = (await conn.execute(text(
            "SELECT count(*) FROM job_entities WHERE job_id = :id"
        ), {"id": OLD})).scalar()
        scores = (await conn.execute(text(
            "SELECT score_version, role_path, reasoning->>'skills_missing' FROM job_scores WHERE job_id = :id"
        ), {"id": US_ONLY})).all()

    assert entity == (["Roadmapping", "SQL"], ["US"], True, "mid")
    assert short_enriched is True
    assert old_entity == 0
    assert len(scores) == 2
    assert all(v == 2 and path == "general" for v, path, _ in scores)


async def test_hard_filters_are_per_user(client):
    await client.get("/api/v1/cron/enrich", params={"limit": 10})

    nigeria = await _inbox(client, NIGERIA_USER)
    us = await _inbox(client, US_USER)

    # US-only remote role: hidden from the user living in Nigeria.
    assert str(US_ONLY) not in nigeria
    assert str(US_ONLY) in us
    # UK role without sponsorship: hidden only from the user who needs UK sponsorship.
    assert str(UK_NO_SPONSOR) in nigeria
    assert str(UK_NO_SPONSOR) not in us
    # Salary below the user's minimum, same currency: hidden only for that user.
    assert str(LOW_SALARY) in nigeria
    assert str(LOW_SALARY) not in us
    # No restrictions at all: visible to both.
    assert str(SHORT) in nigeria and str(SHORT) in us

    # The dashboard count uses the same filters as the inbox.
    for user, inbox in ((NIGERIA_USER, nigeria), (US_USER, us)):
        overview = (await client.get(
            "/api/v1/analytics/overview", headers={"x-test-user": str(user)}
        )).json()
        assert overview["jobs_discovered"] == len(inbox)


async def test_review_top_matches_respects_daily_cap(client, monkeypatch):
    from app.core.database import engine
    from app.services.scoring import deep_scorer

    await client.get("/api/v1/cron/enrich", params={"limit": 10})
    await client.post(f"/api/v1/jobs/{SHORT}/dismiss", headers={"x-test-user": str(US_USER)})
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE job_scores SET overall_fit = 90"))

    reviewed: list[tuple[str, str]] = []

    async def fake_review(db, job_id, user_id, force=False):
        reviewed.append((user_id, job_id))
        await db.execute(text(
            "UPDATE job_scores SET deep_score_json = CAST(:deep AS jsonb) "
            "WHERE job_id = :job AND user_id = :user"
        ), {"deep": json.dumps({"summary": "fits", "scored_at": datetime.now(timezone.utc).isoformat()}),
            "job": job_id, "user": user_id})
        return {}

    monkeypatch.setattr(deep_scorer, "run_deep_score", fake_review)

    first = (await client.get("/api/v1/cron/review-top-matches", params={"per_user_daily": 2})).json()
    assert first["failed"] == 0
    us_reviews = sorted(job for user, job in reviewed if user == str(US_USER))
    ng_reviews = sorted(job for user, job in reviewed if user == str(NIGERIA_USER))
    # US user: SHORT is dismissed, UK_NO_SPONSOR and LOW_SALARY are filtered
    # out, OLD is too old, so only the US-only role qualifies.
    assert us_reviews == [str(US_ONLY)]
    # Nigeria user: US_ONLY is filtered out; the cap stops at two reviews.
    assert len(ng_reviews) == 2
    assert str(US_ONLY) not in ng_reviews

    second = (await client.get("/api/v1/cron/review-top-matches", params={"per_user_daily": 2})).json()
    assert second["queued"] == 0
    assert len(reviewed) == 3


async def test_jobs_in_an_inbox_are_read_first(client, monkeypatch):
    from app.core.database import engine
    from app.services.enrichment import job_enricher

    # A newer job nobody matched, and an older one that's in a user's inbox.
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE jobs SET raw_description = :d WHERE id IN (:a, :b)"
        ), {"d": LONG_DESCRIPTION, "a": UK_NO_SPONSOR, "b": LOW_SALARY})
        await conn.execute(text(
            "UPDATE jobs SET discovered_at = now() - interval '5 days' WHERE id = :id"
        ), {"id": UK_NO_SPONSOR})
        await conn.execute(text(
            "UPDATE job_entities SET enriched_at = NULL WHERE job_id IN (:a, :b)"
        ), {"a": UK_NO_SPONSOR, "b": LOW_SALARY})
        # The fixture scored every job; only the older job clears the inbox bar.
        await conn.execute(text("UPDATE job_scores SET overall_fit = 20"))
        await conn.execute(text(
            "UPDATE job_scores SET overall_fit = 72 WHERE job_id = :j AND user_id = :u"
        ), {"j": UK_NO_SPONSOR, "u": NIGERIA_USER})

    result = await job_enricher.enrich_pending_jobs(limit=1)
    assert client.extracted_calls == [UK_NO_SPONSOR]
    assert result.enriched == 1
