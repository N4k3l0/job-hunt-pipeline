"""Applications with nothing left to do move out of the way: sent ones
with no reply for 30 days, and unsent ones whose job closed (Apply for me,
and resumes approved but never marked applied)."""

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

USER = uuid.UUID("00000000-0000-0000-0000-0000000f0101")
NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


async def test_quiet_and_closed_applications_move_out_of_the_way():
    from app.core.database import async_session, engine
    from app.services.tracking.quiet import JOB_CLOSED, close_quiet_applications

    ids = {name: uuid.uuid4() for name in (
        "old_sent", "new_sent", "interview", "closed_unsent", "open_unsent", "closed_approved", "closed_sent",
        "sent_undated",
    )}
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE auto_applications, application_tracking, jobs, users CASCADE"))
        await conn.execute(text("INSERT INTO users (id, email, name, role) VALUES (:u, 'q@test.dev', 'Q', 'user')"), {"u": USER})
        for name, job_id in ids.items():
            status = "expired" if name.startswith("closed_") else "scored"
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, status, discovered_at) VALUES (:id, 'Acme', :t, :s, :d)"
            ), {"id": job_id, "t": name, "s": status, "d": NOW - timedelta(days=60)})
        for name, status, days in (
            ("old_sent", "applied", 45), ("new_sent", "applied", 5), ("interview", "interviewing", 45),
            ("closed_approved", "approved", 5), ("closed_sent", "applied", 5),
        ):
            await conn.execute(text(
                "INSERT INTO application_tracking (id, user_id, job_id, status, applied_at, follow_up_date) "
                "VALUES (gen_random_uuid(), :u, :j, :s, :at, :fu)"
            ), {"u": USER, "j": ids[name], "s": status, "at": NOW - timedelta(days=days), "fu": (NOW - timedelta(days=days - 7)).date()})
        # Sent through the app before sending set a follow-up date.
        await conn.execute(text(
            "INSERT INTO application_tracking (id, user_id, job_id, status, applied_at) "
            "VALUES (gen_random_uuid(), :u, :j, 'applied', :at)"
        ), {"u": USER, "j": ids["sent_undated"], "at": NOW - timedelta(days=2)})
        for name in ("closed_unsent", "open_unsent"):
            await conn.execute(text(
                "INSERT INTO auto_applications (id, user_id, job_id, status, answers) VALUES (gen_random_uuid(), :u, :j, 'needs_you', '{}')"
            ), {"u": USER, "j": ids[name]})

    async with async_session() as db:
        assert await close_quiet_applications(db, now=NOW) == {"no_reply": 1, "job_closed": 2, "follow_up_dated": 1}

    async with engine.connect() as conn:
        tracked = dict((await conn.execute(text(
            "SELECT j.title, t.status || '/' || coalesce(t.follow_up_date::text, '-') FROM application_tracking t JOIN jobs j ON j.id = t.job_id"
        ))).all())
        applications = dict((await conn.execute(text(
            "SELECT j.title, a.status || '/' || coalesce(a.error, '') FROM auto_applications a JOIN jobs j ON j.id = a.job_id"
        ))).all())
    assert tracked["old_sent"] == "ghosted/-"  # no reply for 45 days: Closed, no more follow-up
    assert tracked["new_sent"].startswith("applied/")
    assert tracked["interview"].startswith("interviewing/")  # never touched once they replied
    assert tracked["closed_approved"] == "archived/-"  # never sent, and the job closed
    assert tracked["closed_sent"].startswith("applied/")  # sent: the company can still reply
    assert tracked["sent_undated"] == f"applied/{(NOW + timedelta(days=5)).date()}"  # a week after sending
    assert applications == {"closed_unsent": f"cancelled/{JOB_CLOSED}", "open_unsent": "needs_you/"}
