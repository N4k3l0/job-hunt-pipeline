"""Age-based stale cleanup must not expire jobs a user has applied to."""

import uuid

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

ADMIN = uuid.UUID("00000000-0000-0000-0000-0000000000ad")
OLD_APPLIED = uuid.UUID("30000000-0000-0000-0000-000000000001")
OLD_UNTOUCHED = uuid.UUID("30000000-0000-0000-0000-000000000002")


async def test_cleanup_skips_jobs_with_applications():
    from app.main import app
    from app.api.deps import require_admin
    from app.core.database import engine
    from app.models.user import User

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE user_job_states, application_tracking, job_scores, jobs, users CASCADE"
        ))
        await conn.execute(text(
            "INSERT INTO users (id, email, name, role) VALUES (:id, 'admin@test.dev', 'Admin', 'admin')"
        ), {"id": ADMIN})
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, status, discovered_at) VALUES "
            "(:applied, 'Acme', 'Old applied', 'scored', now() - interval '90 days'), "
            "(:untouched, 'Acme', 'Old untouched', 'scored', now() - interval '90 days')"
        ), {"applied": OLD_APPLIED, "untouched": OLD_UNTOUCHED})
        await conn.execute(text(
            "INSERT INTO application_tracking (id, job_id, user_id, status) "
            "VALUES (gen_random_uuid(), :job, :user, 'applied')"
        ), {"job": OLD_APPLIED, "user": ADMIN})

    app.dependency_overrides[require_admin] = lambda: User(id=ADMIN, email="admin@test.dev", name="Admin", role="admin")
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            preview = (await client.get("/api/v1/auth/admin/stale-jobs/preview", params={"days": 30})).json()
            assert preview["would_expire"] == 1
            r = await client.post("/api/v1/auth/admin/stale-jobs/cleanup", params={"days": 30})
            assert r.json()["expired"] == 1
    finally:
        app.dependency_overrides.clear()

    async with engine.connect() as conn:
        rows = dict((await conn.execute(text("SELECT title, status FROM jobs"))).all())
    assert rows == {"Old applied": "scored", "Old untouched": "expired"}
