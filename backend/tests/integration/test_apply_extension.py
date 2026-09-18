"""The browser extension: the fill-in it gets once answers are approved,
and marking the application sent, from the extension or the app page."""

import json
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

USER = uuid.UUID("00000000-0000-0000-0000-00000000e001")
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-00000000e002")
JOB = uuid.UUID("00000000-0000-0000-0000-0000000e0001")
JOB_2 = uuid.UUID("00000000-0000-0000-0000-0000000e0002")

FORM = {"questions": [
    {"required": True, "label": "First Name", "fields": [{"name": "first_name", "type": "input_text"}]},
    {"required": True, "label": "Resume/CV", "fields": [{"name": "resume", "type": "input_file"}]},
    {"required": False, "label": "Cover Letter", "fields": [{"name": "cover_letter", "type": "input_file"}]},
    {"required": True, "label": "How did you hear about this job?", "fields": [
        {"name": "question_hear", "type": "multi_value_single_select",
         "values": [{"label": "LinkedIn", "value": 11}, {"label": "Job board", "value": 12}]}]},
]}


@pytest.fixture
async def client(monkeypatch):
    from app.api.deps import get_current_user_id
    from app.core.config import get_settings
    from app.core.database import engine
    from app.main import app
    from app.services.auto_apply import extension, prepare

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE saved_answers, auto_applications, application_tracking, user_job_states, job_scores, "
            "resumes, candidate_work_history, candidate_profiles, jobs, job_sources, users CASCADE"
        ))
        for user_id, email in ((USER, "ada@test.dev"), (OTHER_USER, "other@test.dev")):
            await conn.execute(text(
                "INSERT INTO users (id, email, name, role) VALUES (:id, :email, 'Ada Obi', 'user')"
            ), {"id": user_id, "email": email})
            await conn.execute(text(
                "INSERT INTO candidate_profiles (id, user_id, home_country, links) VALUES (gen_random_uuid(), :u, 'NG', '{}'::jsonb)"
            ), {"u": user_id})
        await conn.execute(text(
            "INSERT INTO resumes (id, user_id, version_name, source_type, file_url, parsed_at) "
            "VALUES (gen_random_uuid(), :u, 'Main', 'pdf', 'ada/abc.pdf', now())"
        ), {"u": USER})
        for job_id, number in ((JOB, "301"), (JOB_2, "302")):
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, status, job_url, country) "
                "VALUES (:id, 'Stripe', 'Product Manager', 'scored', :url, 'US')"
            ), {"id": job_id, "url": f"https://job-boards.greenhouse.io/stripe/jobs/{number}"})

    async def no_drafts(items, facts_text, job):
        return {}

    async def fake_signed_url(bucket, path, expires_in=600):
        return f"https://storage.test/{bucket}/{path}?token=signed"

    uploaded: dict[str, bytes] = {}

    async def fake_upload(bucket, path, content, content_type):
        uploaded[path] = content
        return path

    monkeypatch.setattr(prepare, "http_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=FORM))))
    monkeypatch.setattr(prepare, "draft_answers", no_drafts)
    monkeypatch.setattr(extension, "signed_url", fake_signed_url)
    monkeypatch.setattr(extension, "upload_file", fake_upload)
    monkeypatch.setattr(extension, "api_public_url", lambda: "https://api.test")
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "test-secret")

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-test-user": str(USER)},
    ) as c:
        c.uploaded = uploaded
        yield c
    app.dependency_overrides.clear()


async def _tracking(job_id):
    from app.core.database import engine
    async with engine.connect() as conn:
        return (await conn.execute(text(
            "SELECT status FROM application_tracking WHERE user_id = :u AND job_id = :j"
        ), {"u": USER, "j": job_id})).scalars().all()


async def test_fill_in_then_the_extension_reports_it_sent(client):
    app_id = (await client.post(f"/api/v1/auto-apply/jobs/{JOB}")).json()["id"]

    # Not before the answers are approved.
    r = await client.get(f"/api/v1/auto-apply/{app_id}/fill")
    assert r.status_code == 409 and "Approve" in r.json()["detail"]

    r = await client.put(f"/api/v1/auto-apply/{app_id}/answers", json={"answers": {"question_hear": "12"}, "approve": True})
    assert r.json()["status"] == "queued", r.text

    r = await client.get(f"/api/v1/auto-apply/{app_id}/fill")
    assert r.status_code == 200, r.text
    fill = r.json()
    fields = {f["key"]: f for f in fill["fields"]}
    assert fill["ats"] == "greenhouse" and fill["form_url"] == "https://job-boards.greenhouse.io/stripe/jobs/301"
    assert fill["job"] == {"title": "Product Manager", "company": "Stripe"}
    assert fields["first_name"]["value"] == "Ada"
    assert fields["question_hear"]["value"] == "12" and fields["question_hear"]["options"][1]["label"] == "Job board"
    assert fields["resume"]["kind"] == "resume" and fields["cover_letter"]["kind"] == "cover_letter"
    assert fill["resume"] == {
        "url": "https://storage.test/resumes/ada/abc.pdf?token=signed",
        "filename": "Ada Obi Resume.pdf",
        "content_type": "application/pdf",
    }
    assert fill["sent_url"] == f"https://api.test/api/v1/auto-apply/{app_id}/sent-by-extension"

    # Someone else can't read it.
    other = {"x-test-user": str(OTHER_USER)}
    assert (await client.get(f"/api/v1/auto-apply/{app_id}/fill", headers=other)).status_code == 404

    # The token only works for this application.
    other_app = (await client.post(f"/api/v1/auto-apply/jobs/{JOB_2}")).json()["id"]
    r = await client.post(f"/api/v1/auto-apply/{other_app}/sent-by-extension", json={"token": fill["sent_token"]})
    assert r.status_code == 403
    r = await client.post(f"/api/v1/auto-apply/{app_id}/sent-by-extension", json={"token": "nope"})
    assert r.status_code == 403

    r = await client.post(f"/api/v1/auto-apply/{app_id}/sent-by-extension", json={"token": fill["sent_token"]}, headers={})
    assert r.status_code == 200 and r.json() == {"status": "submitted"}
    body = (await client.get(f"/api/v1/auto-apply/{app_id}")).json()
    assert body["status"] == "submitted" and body["submitted_at"]
    assert await _tracking(JOB) == ["applied"]

    # Reporting twice changes nothing; filling in again is refused.
    r = await client.post(f"/api/v1/auto-apply/{app_id}/sent-by-extension", json={"token": fill["sent_token"]})
    assert r.status_code == 200
    assert await _tracking(JOB) == ["applied"]
    r = await client.get(f"/api/v1/auto-apply/{app_id}/fill")
    assert r.status_code == 409 and "already been sent" in r.json()["detail"]


async def test_user_marks_it_sent_themselves(client):
    app_id = (await client.post(f"/api/v1/auto-apply/jobs/{JOB}")).json()["id"]
    other = {"x-test-user": str(OTHER_USER)}
    assert (await client.post(f"/api/v1/auto-apply/{app_id}/sent", headers=other)).status_code == 404

    r = await client.post(f"/api/v1/auto-apply/{app_id}/sent")
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    assert await _tracking(JOB) == ["applied"]

    cancelled = (await client.post(f"/api/v1/auto-apply/jobs/{JOB_2}")).json()["id"]
    await client.post(f"/api/v1/auto-apply/{cancelled}/cancel")
    r = await client.post(f"/api/v1/auto-apply/{cancelled}/sent")
    assert r.status_code == 422
    assert await _tracking(JOB_2) == []


TAILORED = {
    "tailored_summary": "I build LLM systems that ship.",
    "selected_experience": [
        {"company": "Acme", "title": "Product Manager", "dates": "2019 - Present",
         "bullets": ["Shipped the payments rewrite."]}
    ],
    "highlighted_skills": ["Python", "LLMs"],
}


async def test_a_tailored_resume_and_cover_letter_are_attached(client):
    """When the job has a tailored resume, that's what goes to the employer
    — as a PDF the app draws itself — with the cover letter the form asks for."""
    app_id = (await client.post(f"/api/v1/auto-apply/jobs/{JOB}")).json()["id"]

    from app.core.database import engine
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO tailored_applications (id, job_id, user_id, tailored_resume_json, tailored_summary, "
            "cover_letter, approval_status) VALUES (gen_random_uuid(), :j, :u, CAST(:r AS jsonb), :s, :c, 'ready')"
        ), {"j": JOB, "u": USER, "r": json.dumps(TAILORED), "s": TAILORED["tailored_summary"],
            "c": "Dear hiring team,\n\nI'd like to apply.\n\nAda"})

    documents = (await client.get(f"/api/v1/auto-apply/{app_id}/documents")).json()
    assert documents["tailored"] is True
    assert documents["resume"]["filename"] == "Ada Obi Resume.pdf"
    assert documents["cover_letter"]["filename"] == "Ada Obi Cover Letter.pdf"

    # Both are PDFs the app generated, not the file on the profile.
    written = client.uploaded
    assert len(written) == 2
    for path, content in written.items():
        assert path.startswith(f"applications/{USER}/{app_id}-")
        assert content.startswith(b"%PDF")
    assert all(len(content) > 800 for content in written.values())
