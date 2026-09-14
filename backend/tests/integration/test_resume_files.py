"""Resume files are private: uploads get generated names, owners open them
through short-lived links, and deleting a resume deletes its file."""

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

USER = uuid.UUID("00000000-0000-0000-0000-00000000f101")
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-00000000f102")
PUBLIC_URL = f"https://x.supabase.co/storage/v1/object/public/resumes/{USER}/Old%20CV.pdf"


@pytest.fixture
async def client(monkeypatch):
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine
    from app.services import storage
    from app.workers import parsing_tasks

    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE resumes, candidate_profiles, users CASCADE"))
        for user in (USER, OTHER_USER):
            await conn.execute(text(
                "INSERT INTO users (id, email, name, role) VALUES (:u, :e, 'R', 'user')"
            ), {"u": user, "e": f"{user}@test.dev"})

    calls: dict[str, list] = {"upload": [], "signed": [], "delete": []}

    async def fake_upload(bucket, path, content, content_type):
        calls["upload"].append((bucket, path))
        return path

    async def fake_signed(bucket, path, expires_in=600):
        calls["signed"].append((bucket, path))
        return f"https://signed.example/{path}?token=t"

    async def fake_delete(bucket, path):
        calls["delete"].append((bucket, path))

    async def fake_parse(resume_id, user_id):
        return None

    monkeypatch.setattr(storage, "upload_file", fake_upload)
    monkeypatch.setattr(storage, "signed_url", fake_signed)
    monkeypatch.setattr(storage, "delete_file", fake_delete)
    monkeypatch.setattr(parsing_tasks, "_parse_resume_async", fake_parse)

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"x-test-user": str(USER)}) as c:
        c.calls = calls
        yield c
    app.dependency_overrides.clear()


async def _upload(client, filename="../../My CV.pdf"):
    r = await client.post(
        "/api/v1/candidates/resumes",
        files={"file": (filename, b"%PDF-1.4 test", "application/pdf")},
        data={"version_name": "Main"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_upload_open_and_delete(client):
    body = await _upload(client)
    assert "file_url" not in body

    bucket, path = client.calls["upload"][0]
    assert bucket == "resumes"
    folder, name = path.split("/")
    assert folder == str(USER)
    assert name.endswith(".pdf") and "CV" not in name and ".." not in path

    r = await client.get(f"/api/v1/candidates/resumes/{body['id']}/download")
    assert r.status_code == 200, r.text
    assert r.json() == {"url": f"https://signed.example/{path}?token=t", "expires_in": 600}

    # Another user can't get a link to it.
    r = await client.get(f"/api/v1/candidates/resumes/{body['id']}/download", headers={"x-test-user": str(OTHER_USER)})
    assert r.status_code == 404
    assert len(client.calls["signed"]) == 1

    r = await client.delete(f"/api/v1/candidates/resumes/{body['id']}")
    assert r.status_code == 204
    assert client.calls["delete"] == [("resumes", path)]


async def test_rows_saved_with_public_urls(client):
    from app.core.database import engine

    ids = [uuid.uuid4(), uuid.uuid4()]
    async with engine.begin() as conn:
        for resume_id in ids:
            # Two rows sharing one file, as same-named uploads used to.
            await conn.execute(text(
                "INSERT INTO resumes (id, user_id, version_name, source_type, file_url) "
                "VALUES (:id, :u, 'Old', 'pdf', :url)"
            ), {"id": resume_id, "u": USER, "url": PUBLIC_URL})

    r = await client.get(f"/api/v1/candidates/resumes/{ids[0]}/download")
    assert r.json()["url"] == f"https://signed.example/{USER}/Old CV.pdf?token=t"

    # The file stays while another row still uses it, then goes with the last.
    assert (await client.delete(f"/api/v1/candidates/resumes/{ids[0]}")).status_code == 204
    assert client.calls["delete"] == []
    assert (await client.delete(f"/api/v1/candidates/resumes/{ids[1]}")).status_code == 204
    assert client.calls["delete"] == [("resumes", f"{USER}/Old CV.pdf")]
