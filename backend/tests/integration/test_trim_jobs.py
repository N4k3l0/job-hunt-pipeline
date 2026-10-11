"""Old jobs nobody will look at again lose their stored text; anything a
user worked on keeps it."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

USER = uuid.UUID("00000000-0000-0000-0000-0000000f0001")
NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def job_id(n: int) -> uuid.UUID:
    return uuid.UUID(f"60000000-0000-0000-0000-{n:012d}")


# (number, status, days since found, days since last listed, best score)
JOBS = {
    1: ("expired", 90, 60, 20),    # closed long ago: trimmed
    2: ("expired", 90, 10, 20),    # closed recently: kept
    3: ("scored", 60, 50, 30),     # old, never matched anyone: trimmed
    4: ("scored", 60, 50, 65),     # old but matched someone: kept
    5: ("scored", 10, 1, 30),      # new: kept
    6: ("duplicate", 90, 60, None),  # an old duplicate: trimmed
    7: ("expired", 90, 60, 20),    # closed, but the user rated it: kept
    8: ("expired", 90, 60, 20),    # closed, but the user applied with it: kept
}


async def test_only_old_untouched_jobs_lose_their_text():
    from app.core.database import async_session, engine
    from app.services.maintenance.trim_jobs import trim_old_jobs

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE auto_applications, job_ratings, job_scores, jobs, users CASCADE"))
        await conn.execute(text("INSERT INTO users (id, email, name, role) VALUES (:u, 'u@test.dev', 'U', 'user')"), {"u": USER})
        for n, (status, found, seen, fit) in JOBS.items():
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, status, discovered_at, last_seen_at, raw_description, raw_description_en, raw_content) "
                "VALUES (:id, 'Acme', :title, :status, :found, :seen, 'A long description.', 'In English.', '<html>')"
            ), {"id": job_id(n), "title": f"Job {n}", "status": status,
                "found": NOW - timedelta(days=found), "seen": NOW - timedelta(days=seen)})
            if fit is not None:
                await conn.execute(text(
                    "INSERT INTO job_scores (id, job_id, user_id, role_path, title_score, skill_score, seniority_score, "
                    "industry_score, geo_score, remote_score, salary_score, visa_score, overall_fit, priority, score_version) "
                    "VALUES (gen_random_uuid(), :j, :u, 'general', 0, 0, 0, 0, 0, 0, 0, 0, :fit, 'low', 5)"
                ), {"j": job_id(n), "u": USER, "fit": fit})
        await conn.execute(text(
            "INSERT INTO job_ratings (id, user_id, job_id, rating) VALUES (gen_random_uuid(), :u, :j, 'bad')"
        ), {"u": USER, "j": job_id(7)})
        await conn.execute(text(
            "INSERT INTO auto_applications (id, user_id, job_id, status, answers) VALUES (gen_random_uuid(), :u, :j, 'submitted', '{}')"
        ), {"u": USER, "j": job_id(8)})

    async with async_session() as db:
        assert await trim_old_jobs(db, now=NOW) == {"trimmed": 3}
    async with async_session() as db:
        assert await trim_old_jobs(db, now=NOW) == {"trimmed": 0}  # each job once

    async with engine.connect() as conn:
        rows = dict((await conn.execute(text(
            "SELECT title, raw_description IS NULL AND raw_description_en IS NULL AND raw_content IS NULL FROM jobs"
        ))).all())
    assert {title for title, emptied in rows.items() if emptied} == {"Job 1", "Job 3", "Job 6"}
    assert len(rows) == 8  # the rows stay, so nothing is added twice
