"""Closed jobs leave the inbox: last_seen_at tracking on ingest, the two
expiry rules and their safety waits, and the link checker working through
the whole catalog."""

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

NOW = datetime.now(timezone.utc)
USER = uuid.UUID("00000000-0000-0000-0000-00000000f001")


def days_ago(n):
    return NOW - timedelta(days=n)


async def _reset(conn):
    await conn.execute(text(
        "TRUNCATE user_job_states, application_tracking, job_scores, candidate_profiles, "
        "jobs, job_sources, users CASCADE"
    ))
    await conn.execute(text(
        "INSERT INTO users (id, email, name, role) VALUES (:id, 'f@test.dev', 'F', 'user')"
    ), {"id": USER})


async def _source(conn, name) -> uuid.UUID:
    source_id = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO job_sources (id, name, source_type, is_active) VALUES (:id, :name, 'api', true)"
    ), {"id": source_id, "name": name})
    return source_id


async def _job(conn, *, source_id, discovered, last_seen, title="Job", url=None, status="scored") -> uuid.UUID:
    job_id = uuid.uuid4()
    await conn.execute(text(
        "INSERT INTO jobs (id, source_id, company, title, status, discovered_at, last_seen_at, job_url) "
        "VALUES (:id, :source, 'Acme', :title, :status, :discovered, :seen, :url)"
    ), {"id": job_id, "source": source_id, "title": title, "status": status,
        "discovered": discovered, "seen": last_seen, "url": url})
    return job_id


async def _statuses(conn) -> dict:
    return dict((await conn.execute(text("SELECT title, status FROM jobs"))).all())


async def test_ingest_refreshes_last_seen_for_jobs_still_listed():
    from app.core.database import engine
    from app.workers.discovery_tasks import _ingest_raw_jobs

    async with engine.begin() as conn:
        await _reset(conn)
        source_id = await _source(conn, "remotive")
        await _job(conn, source_id=source_id, discovered=days_ago(20), last_seen=None,
                   title="Still listed", url="https://jobs.example.com/1")

    await _ingest_raw_jobs([
        {"source_name": "remotive", "company": "Other", "title": "Renamed but same URL",
         "job_url": "https://jobs.example.com/1", "raw_description": ""},
        {"source_name": "remotive", "company": "Acme", "title": "Brand new",
         "job_url": "https://jobs.example.com/2", "raw_description": ""},
    ])

    async with engine.connect() as conn:
        rows = dict((await conn.execute(text("SELECT title, last_seen_at FROM jobs"))).all())
    assert set(rows) == {"Still listed", "Brand new"}
    assert rows["Still listed"] is not None and rows["Still listed"] > days_ago(1)
    assert rows["Brand new"] is not None


async def test_expiry_rules():
    from app.core.database import engine, async_session
    from app.services.maintenance.job_expiry import expire_stale_jobs

    async with engine.begin() as conn:
        await _reset(conn)
        curated = await _source(conn, "curated")
        other = await _source(conn, "jsearch")
        # Curated board tracking has run for 10 days and saw jobs today.
        await _job(conn, source_id=curated, discovered=days_ago(10), last_seen=NOW, title="Board: still listed")
        await _job(conn, source_id=curated, discovered=days_ago(12), last_seen=days_ago(10), title="Board: taken down")
        await _job(conn, source_id=curated, discovered=days_ago(9), last_seen=days_ago(3), title="Board: missed 3 days")
        # Other sources.
        await _job(conn, source_id=other, discovered=days_ago(60), last_seen=days_ago(40), title="Old, unlisted")
        await _job(conn, source_id=other, discovered=days_ago(60), last_seen=days_ago(5), title="Old, still listed")
        await _job(conn, source_id=other, discovered=days_ago(20), last_seen=None, title="Recent")
        applied = await _job(conn, source_id=other, discovered=days_ago(90), last_seen=None, title="Old, applied")
        tailored = await _job(conn, source_id=other, discovered=days_ago(90), last_seen=None, title="Old, tailored")
        preparing = await _job(conn, source_id=other, discovered=days_ago(90), last_seen=None, title="Old, Apply for me")
        await conn.execute(text(
            "INSERT INTO tailored_applications (id, job_id, user_id, approval_status) "
            "VALUES (gen_random_uuid(), :j, :u, 'ready')"
        ), {"j": tailored, "u": USER})
        await conn.execute(text(
            "INSERT INTO auto_applications (id, job_id, user_id, status) VALUES (gen_random_uuid(), :j, :u, 'needs_you')"
        ), {"j": preparing, "u": USER})
        shortlisted = await _job(conn, source_id=other, discovered=days_ago(90), last_seen=None, title="Old, shortlisted")
        await conn.execute(text(
            "INSERT INTO application_tracking (id, job_id, user_id, status) VALUES (gen_random_uuid(), :j, :u, 'applied')"
        ), {"j": applied, "u": USER})
        await conn.execute(text(
            "INSERT INTO user_job_states (id, job_id, user_id, status) VALUES (gen_random_uuid(), :j, :u, 'shortlisted')"
        ), {"j": shortlisted, "u": USER})

    async with async_session() as db:
        preview = await expire_stale_jobs(db, dry_run=True, now=NOW)
    assert preview["gone_from_board"] == 1
    assert preview["old_and_unseen"] == 1
    async with engine.connect() as conn:
        assert "expired" not in (await _statuses(conn)).values()  # dry run changed nothing

    async with async_session() as db:
        result = await expire_stale_jobs(db, now=NOW)
    assert (result["gone_from_board"], result["old_and_unseen"]) == (1, 1)

    async with engine.connect() as conn:
        statuses = await _statuses(conn)
    assert statuses["Board: taken down"] == "expired"
    assert statuses["Old, unlisted"] == "expired"
    for title in ("Board: still listed", "Board: missed 3 days", "Old, still listed", "Recent",
                  "Old, applied", "Old, shortlisted", "Old, tailored", "Old, Apply for me"):
        assert statuses[title] == "scored", title


async def test_expiry_waits_until_tracking_has_run():
    from app.core.database import engine, async_session
    from app.services.maintenance.job_expiry import expire_stale_jobs

    async with engine.begin() as conn:
        await _reset(conn)
        curated = await _source(conn, "curated")
        other = await _source(conn, "jsearch")
        # Tracking only started today: nothing has had a chance to be re-listed.
        await _job(conn, source_id=curated, discovered=days_ago(30), last_seen=NOW, title="Board job")
        await _job(conn, source_id=curated, discovered=days_ago(30), last_seen=None, title="Board job, not yet seen")
        await _job(conn, source_id=other, discovered=days_ago(200), last_seen=None, title="Very old")

    async with async_session() as db:
        result = await expire_stale_jobs(db, now=NOW)
    assert (result["gone_from_board"], result["old_and_unseen"]) == (0, 0)


async def test_link_checker_works_through_catalog(monkeypatch):
    from app.core.database import engine, async_session
    from app.services.maintenance import url_verifier

    async with engine.begin() as conn:
        await _reset(conn)
        source = await _source(conn, "remotive")
        for i in range(4):
            await _job(conn, source_id=source, discovered=days_ago(50 - i), last_seen=None,
                       title=f"Job {i}", url=f"https://jobs.example.com/{i}")
        tracked = await _job(conn, source_id=source, discovered=days_ago(99), last_seen=None,
                             title="Tracked", url="https://jobs.example.com/tracked")
        await conn.execute(text(
            "INSERT INTO application_tracking (id, job_id, user_id, status) VALUES (gen_random_uuid(), :j, :u, 'applied')"
        ), {"j": tracked, "u": USER})

    probed: list[str] = []

    async def fake_probe(client, url, sem):
        probed.append(url)
        return "dead" if url.endswith("/1") else "alive"

    monkeypatch.setattr(url_verifier, "_probe", fake_probe)

    async with async_session() as db:
        first = await url_verifier.verify_batch(db, limit=2)
    async with async_session() as db:
        second = await url_verifier.verify_batch(db, limit=2)

    # Oldest two first, then the next two: the checker moves on instead of
    # re-probing the same jobs, and never probes the tracked job.
    assert probed == [f"https://jobs.example.com/{i}" for i in (0, 1, 2, 3)]
    assert (first["expired"], second["expired"]) == (1, 0)
    async with engine.connect() as conn:
        statuses = await _statuses(conn)
        unchecked = (await conn.execute(text(
            "SELECT count(*) FROM jobs WHERE last_checked_at IS NULL AND title LIKE 'Job %'"
        ))).scalar()
    assert statuses["Job 1"] == "expired"
    assert statuses["Tracked"] == "scored"
    assert unchecked == 0
