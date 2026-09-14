"""Apply for me: preparing an application, answering what's left,
queueing it, and reusing answers on the next form."""

import uuid

import httpx
import pytest
from fastapi import Header
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.services.auto_apply.answers import answer
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL or "test" not in (make_url(TEST_DATABASE_URL).database or ""),
    reason="set TEST_DATABASE_URL to a disposable *test* database",
)

USER = uuid.UUID("00000000-0000-0000-0000-00000000a001")
OTHER_USER = uuid.UUID("00000000-0000-0000-0000-00000000a002")
JOB_A = uuid.UUID("00000000-0000-0000-0000-0000000a0001")
JOB_B = uuid.UUID("00000000-0000-0000-0000-0000000a0002")
JOB_UNSUPPORTED = uuid.UUID("00000000-0000-0000-0000-0000000a0003")
JOB_CLOSED = uuid.UUID("00000000-0000-0000-0000-0000000a0004")

HEAR = {"required": True, "label": "How did you hear about this job?", "fields": [
    {"name": "question_hear", "type": "multi_value_single_select",
     "values": [{"label": "LinkedIn", "value": 11}, {"label": "Job board", "value": 12}]}]}

FORMS = {
    "111": {"questions": [
        {"required": True, "label": "First Name", "fields": [{"name": "first_name", "type": "input_text"}]},
        {"required": True, "label": "Last Name", "fields": [{"name": "last_name", "type": "input_text"}]},
        {"required": True, "label": "Email", "fields": [{"name": "email", "type": "input_text"}]},
        {"required": True, "label": "Phone", "fields": [{"name": "phone", "type": "input_text"}]},
        {"required": True, "label": "Resume/CV", "fields": [{"name": "resume", "type": "input_file"}]},
        {"required": True, "label": "Why Stripe?", "fields": [{"name": "question_why", "type": "textarea"}]},
        HEAR,
        {"required": True, "label": "Have you ever interviewed at Stripe before?", "fields": [
            {"name": "question_interviewed", "type": "multi_value_single_select",
             "values": [{"label": "Yes", "value": 1}, {"label": "No", "value": 0}]}]},
        {"required": True, "label": "Please read the arbitration agreement", "fields": [
            {"name": "question_arb", "type": "multi_value_single_select",
             "values": [{"label": "I have read and agree to the arbitration agreement.", "value": 1}]}]},
    ], "compliance": [{"type": "eeoc", "questions": [
        {"required": False, "label": "Gender", "fields": [{"name": "gender", "type": "multi_value_single_select",
         "values": [{"label": "Female", "value": 1}, {"label": "Decline To Self Identify", "value": 3}]}]}]}]},
    "222": {"questions": [
        {"required": True, "label": "First Name", "fields": [{"name": "first_name", "type": "input_text"}]},
        HEAR,
    ]},
}


def ats_handler(request: httpx.Request) -> httpx.Response:
    job_id = request.url.path.rstrip("/").split("/")[-1]
    if request.url.host == "boards-api.greenhouse.io" and job_id in FORMS:
        return httpx.Response(200, json=FORMS[job_id])
    return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
async def client(monkeypatch):
    from app.main import app
    from app.api.deps import get_current_user_id
    from app.core.database import engine
    from app.services.auto_apply import prepare

    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE saved_answers, auto_applications, application_tracking, user_job_states, job_scores, "
            "resumes, candidate_work_history, candidate_profiles, jobs, job_sources, users CASCADE"
        ))
        for user_id, email in ((USER, "ada@test.dev"), (OTHER_USER, "other@test.dev")):
            await conn.execute(text(
                "INSERT INTO users (id, email, name, role) VALUES (:id, :email, 'Ada Obi', 'user')"
            ), {"id": user_id, "email": email})
        profile_id = uuid.uuid4()
        await conn.execute(text(
            "INSERT INTO candidate_profiles (id, user_id, home_country, current_location, links) "
            "VALUES (:id, :u, 'NG', 'Lagos, Nigeria', '{}'::jsonb)"
        ), {"id": profile_id, "u": USER})
        await conn.execute(text(
            "INSERT INTO candidate_work_history (id, profile_id, company, title, start_date, sort_order) "
            "VALUES (gen_random_uuid(), :p, 'Acme', 'Product Manager', '2019-01-01', 0)"
        ), {"p": profile_id})
        await conn.execute(text(
            "INSERT INTO resumes (id, user_id, version_name, source_type, file_url, parsed_at) "
            "VALUES (gen_random_uuid(), :u, 'Main', 'pdf', 'https://example.com/r.pdf', now())"
        ), {"u": USER})
        for job_id, url in (
            (JOB_A, "https://job-boards.greenhouse.io/acme/jobs/111"),
            (JOB_B, "https://job-boards.greenhouse.io/acme/jobs/222"),
            (JOB_UNSUPPORTED, "https://www.linkedin.com/jobs/view/1"),
            (JOB_CLOSED, "https://job-boards.greenhouse.io/acme/jobs/404"),
        ):
            await conn.execute(text(
                "INSERT INTO jobs (id, company, title, status, job_url, country) "
                "VALUES (:id, 'Stripe', 'Product Manager', 'scored', :url, 'US')"
            ), {"id": job_id, "url": url})

    drafted_for: list[list[str]] = []

    async def fake_drafter(items, facts_text, job):
        drafted_for.append([i["key"] for i in items])
        assert "Product Manager at Acme" in facts_text
        return {"question_why": answer("I led payments work at Acme.", "drafted", "Drafted from your profile.")}

    monkeypatch.setattr(prepare, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(ats_handler)))
    monkeypatch.setattr(prepare, "draft_answers", fake_drafter)

    async def fake_user_id(x_test_user: str = Header()) -> uuid.UUID:
        return uuid.UUID(x_test_user)

    app.dependency_overrides[get_current_user_id] = fake_user_id
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"x-test-user": str(USER)}) as c:
        c.drafted_for = drafted_for
        yield c
    app.dependency_overrides.clear()


def by_key(body):
    return {f["key"]: f for f in body["fields"]}


async def test_prepare_answer_and_queue(client):
    r = await client.post(f"/api/v1/auto-apply/jobs/{JOB_A}")
    assert r.status_code == 200, r.text
    body = r.json()
    app_id = body["id"]
    fields = by_key(body)
    assert body["status"] == "needs_you"
    assert body["ats"] == "greenhouse"
    assert body["form_url"] == "https://job-boards.greenhouse.io/acme/jobs/111"
    assert fields["first_name"]["answer"]["value"] == "Ada" and not fields["first_name"]["needs_attention"]
    assert fields["resume"]["answer"]["value"] == "resume"
    assert fields["gender"]["answer"]["value"] == "3" and not fields["gender"]["needs_attention"]
    assert fields["question_why"]["answer"]["source"] == "drafted" and fields["question_why"]["needs_attention"]
    assert fields["phone"]["needs_attention"] and fields["phone"]["answer"]["value"] is None
    assert fields["question_hear"]["needs_attention"]
    assert fields["question_arb"]["kind"] == "agreement" and fields["question_arb"]["needs_attention"]
    assert fields["question_interviewed"]["needs_attention"]
    assert fields["question_interviewed"]["answer"] is None
    assert body["open_count"] == 5
    # Only questions the rules couldn't answer are drafted. Agreements never
    # are, nor whether the user interviewed there before: no profile says.
    assert client.drafted_for == [["question_why", "question_hear"]]

    # Approving with questions still open is refused and names them.
    r = await client.put(f"/api/v1/auto-apply/{app_id}/answers", json={
        "answers": {"question_why": "I led payments work at Acme."}, "approve": True,
    })
    assert r.status_code == 422
    assert set(r.json()["detail"]["fields"]) == {"phone", "question_hear", "question_interviewed", "question_arb"}

    # An option that isn't on the form is refused.
    r = await client.put(f"/api/v1/auto-apply/{app_id}/answers", json={"answers": {"question_hear": "99"}})
    assert r.status_code == 422

    # Saving without approving keeps it waiting on the user.
    r = await client.put(f"/api/v1/auto-apply/{app_id}/answers", json={"answers": {"phone": "+234 800 111 2222"}})
    assert r.status_code == 200 and r.json()["status"] == "needs_you"
    assert r.json()["open_count"] == 4  # the failed save above changed nothing

    r = await client.put(f"/api/v1/auto-apply/{app_id}/answers", json={
        "answers": {"question_why": "I led payments work at Acme.", "question_hear": "12",
                    "question_interviewed": "0", "question_arb": "1"},
        "approve": True,
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "queued" and r.json()["open_count"] == 0

    from app.core.database import engine
    async with engine.connect() as conn:
        phone = (await conn.execute(text("SELECT phone FROM candidate_profiles WHERE user_id = :u"), {"u": USER})).scalar()
        saved = (await conn.execute(text("SELECT label, answer FROM saved_answers WHERE user_id = :u"), {"u": USER})).all()
    assert phone == "+234 800 111 2222"  # remembered on the profile
    assert sorted((label, answer["labels"]) for label, answer in saved) == [
        ("Have you ever interviewed at Stripe before?", ["No"]),
        ("How did you hear about this job?", ["Job board"]),
    ]

    # The next form asking the same question is answered from memory.
    r = await client.post(f"/api/v1/auto-apply/jobs/{JOB_B}")
    body = r.json()
    assert body["status"] == "queued", body
    assert by_key(body)["question_hear"]["answer"]["source"] == "saved"

    r = await client.get(f"/api/v1/jobs/{JOB_A}")
    assert r.json()["auto_apply"] == {"supported": True, "application_id": app_id, "status": "queued"}

    # Preparing again keeps the user's own answers.
    r = await client.post(f"/api/v1/auto-apply/{app_id}/cancel")
    assert r.json()["status"] == "cancelled"
    r = await client.post(f"/api/v1/auto-apply/jobs/{JOB_A}")
    body = r.json()
    assert body["status"] == "queued"
    assert by_key(body)["question_why"]["answer"]["source"] == "user"


async def test_unsupported_closed_and_private(client):
    r = await client.post(f"/api/v1/auto-apply/jobs/{JOB_UNSUPPORTED}")
    assert r.json()["status"] == "unsupported" and "Greenhouse" in r.json()["error"]

    r = await client.post(f"/api/v1/auto-apply/jobs/{JOB_CLOSED}")
    assert r.json()["status"] == "failed" and r.json()["error"] == "This posting has closed."

    r = await client.get("/api/v1/auto-apply")
    assert len(r.json()) == 2
    app_id = r.json()[0]["id"]

    other = {"x-test-user": str(OTHER_USER)}
    assert (await client.get("/api/v1/auto-apply", headers=other)).json() == []
    assert (await client.get(f"/api/v1/auto-apply/{app_id}", headers=other)).status_code == 404
    assert (await client.post(f"/api/v1/auto-apply/{app_id}/cancel", headers=other)).status_code == 404

    r = await client.get(f"/api/v1/jobs/{JOB_UNSUPPORTED}")
    assert r.json()["auto_apply"]["supported"] is False


async def test_sent_applications_are_left_alone(client):
    r = await client.post(f"/api/v1/auto-apply/jobs/{JOB_B}")
    app_id = r.json()["id"]
    from app.core.database import engine
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE auto_applications SET status = 'submitted' WHERE id = :id"), {"id": app_id})

    r = await client.post(f"/api/v1/auto-apply/jobs/{JOB_B}")
    assert r.json()["status"] == "submitted"
    r = await client.put(f"/api/v1/auto-apply/{app_id}/answers", json={"answers": {"first_name": "Bo"}})
    assert r.status_code == 422
    assert (await client.post(f"/api/v1/auto-apply/{app_id}/cancel")).status_code == 422
