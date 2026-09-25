"""Rate matches: the queue offers the user's own inbox jobs without scores,
ratings are saved per user, and results compare current and proposed
scoring on the rated jobs."""

import uuid
from datetime import datetime, timezone

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000e301")
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-00000000e302")
LONG = "Build retrieval pipelines in Python with LangChain and ship them to production. " * 5


@pytest.fixture
async def client():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE job_ratings, user_job_states, application_tracking, job_scores, candidate_skills, "
            "candidate_work_history, candidate_profiles, jobs, job_sources, users CASCADE"
        ))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:u, 'rate@test.dev', 'R', 'user'), "
            "(:o, 'other@test.dev', 'O', 'user')"
        ), {"u": USER, "o": OTHER_USER})
        for user in (USER, OTHER_USER):
            profile_id = uuid.uuid4()
            await conn.execute(text(
                "INSERT INTO candidate_profiles (id, user_id, target_roles, remote_preference) "
                "VALUES (:p, :u, ARRAY['AI Engineer'], 'any')"
            ), {"p": profile_id, "u": user})
            await conn.execute(text(
                "INSERT INTO candidate_skills (id, profile_id, skill_name, category) VALUES "
                "(gen_random_uuid(), :p, 'Python', 'technical'), (gen_random_uuid(), :p, 'LangChain', 'tool')"
            ), {"p": profile_id})
            await conn.execute(text(
                "INSERT INTO candidate_work_history (id, profile_id, company, title, start_date, sort_order) "
                "VALUES (gen_random_uuid(), :p, 'Prev', 'Senior AI Engineer', '2016-01-01', 0)"
            ), {"p": profile_id})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        yield c
    app.dependency_overrides.clear()


async def _job(title, score, company="Acme", seniority=None, user=USER) -> uuid.UUID:
    from app.core.database import engine

    job_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, remote_type, seniority, raw_description, status, discovered_at) "
            "VALUES (:id, :company, :title, 'full_remote', :seniority, :d, 'scored', :now)"
        ), {"id": job_id, "company": company, "title": title, "seniority": seniority, "d": LONG,
            "now": datetime.now(timezone.utc)})
        await conn.execute(text(
            "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, "
            "seniority_score, industry_score, geo_score, remote_score, salary_score, visa_score, "
            "overall_fit, priority, score_version) "
            "VALUES (gen_random_uuid(), :j, :u, 'general', 0, 5, 0, 0, 0, 0, 0, 0, :fit, 'medium', 2)"
        ), {"j": job_id, "u": user, "fit": score})
    return job_id


async def test_queue_ratings_and_results(client):
    strong = await _job("Senior AI Engineer", 85, seniority="senior")
    unstated_level = await _job("AI Engineer, Search", 70)
    duplicate = await _job("Senior AI Engineer", 80, seniority="senior")  # same company and title as `strong`
    dismissed = await _job("AI Engineer, Voice", 75, company="Voice Co")
    too_low = await _job("AI Engineer, Ads", 20, company="Ads Co")
    await _job("AI Engineer, Other", 90, company="Other Co", user=OTHER_USER)
    await client.post(f"/api/v1/jobs/{dismissed}/dismiss")

    r = await client.get("/api/v1/ratings/queue")
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {j["id"] for j in body["jobs"]}
    assert ids == {str(strong), str(unstated_level)}
    assert str(duplicate) not in ids and str(dismissed) not in ids and str(too_low) not in ids
    assert body["rated"] == 0 and body["target"] == 50
    # The user judges the job, not the score.
    assert all("score" not in j and "overall_fit" not in j for j in body["jobs"])
    assert body["jobs"][0]["description"]

    r = await client.put(f"/api/v1/ratings/{strong}", json={"rating": "good"})
    assert r.status_code == 200 and r.json()["rated"] == 1
    assert (await client.put(f"/api/v1/ratings/{unstated_level}", json={"rating": "maybe"})).status_code == 422
    await client.put(f"/api/v1/ratings/{unstated_level}", json={"rating": "good"})
    await client.put(f"/api/v1/ratings/{unstated_level}", json={"rating": "bad"})  # changed their mind

    assert (await client.get("/api/v1/ratings/queue")).json()["jobs"] == []

    results = (await client.get("/api/v1/ratings/results")).json()
    assert results["rated"] == 2 and results["good"] == 1
    from app.services.scoring.scorer import PROPOSED_SCORE_VERSION, SCORE_VERSION
    assert results["current"]["version"] == SCORE_VERSION
    assert results["current"]["ranking_accuracy"] is not None
    # A proposed version only shows when it differs from the live one.
    if PROPOSED_SCORE_VERSION == SCORE_VERSION:
        assert results["proposed"] is None
    else:
        assert results["proposed"]["version"] == PROPOSED_SCORE_VERSION

    # Other users' ratings are separate.
    other = (await client.get("/api/v1/ratings/results", headers={"x-test-user": str(OTHER_USER)})).json()
    assert other["rated"] == 0

    assert (await client.delete(f"/api/v1/ratings/{unstated_level}")).status_code == 204
    assert [j["id"] for j in (await client.get("/api/v1/ratings/queue")).json()["jobs"]] == [str(unstated_level)]
    assert (await client.put(f"/api/v1/ratings/{uuid.uuid4()}", json={"rating": "good"})).status_code == 404


async def test_results_can_compare_other_versions(client):
    """Before choosing the next scoring, the page can measure several
    versions on the user's ratings at once. Unknown versions are ignored."""
    r = await client.get("/api/v1/ratings/results", params={"compare": "2,3,4,99"})
    assert r.status_code == 200, r.text
    compared = r.json().get("compared") or {}
    assert set(compared) == {"2", "3", "4", "5"}
    for metrics in compared.values():
        assert "ranking_accuracy" in metrics
