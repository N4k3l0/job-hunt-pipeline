"""The job page's description comes back sanitized."""

import uuid

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000f401")


async def test_job_detail_sends_sanitized_description():
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine

    job_id, translated_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE jobs, users CASCADE"))
        await conn.execute(text("INSERT INTO users (id, email, name, role) VALUES (:u, 'html@test.dev', 'H', 'user')"), {"u": USER})
        await conn.execute(text(
            "INSERT INTO jobs (id, company, title, status, raw_description, raw_description_en) VALUES "
            "(:a, 'Acme', 'Engineer', 'scored', :evil, NULL), (:b, 'Acme', 'Ingenieur', 'scored', '<p>Hallo</p>', :en)"
        ), {"a": job_id, "b": translated_id,
            "evil": '&lt;p onclick="x()"&gt;Build&lt;/p&gt;&lt;img src=x onerror="steal()"&gt;',
            "en": "<p>Hello</p><script>steal()</script>"})

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-test-user": str(USER)},
        ) as client:
            job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
            translated = (await client.get(f"/api/v1/jobs/{translated_id}")).json()
    finally:
        app.dependency_overrides.clear()

    # Escaped HTML is decoded, then sanitized like any other.
    assert job["description_html"] == "<p>Build</p>"
    assert translated["description_html"] == "<p>Hello</p>"
