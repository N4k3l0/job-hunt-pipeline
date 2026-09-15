import uuid

from app.services.notifications import digest as digest_module
from app.services.notifications.digest import (
    Digest, DigestJob, FollowUp, WaitingApplication, digest_subject, render_digest, unsubscribe_token,
    valid_unsubscribe_token,
)


def _digest(**kwargs):
    return Digest(name="Ada", email="ada@test.dev", **kwargs)


def test_subject_says_what_is_new():
    assert digest_subject(_digest(new_match_count=1)) == "1 new job match"
    assert digest_subject(_digest(
        new_match_count=5, needs_you=[WaitingApplication(uuid.uuid4(), "AI Engineer", "Acme", 3)],
        follow_ups=[FollowUp("PM", "Globex", None), FollowUp("PM2", "Initech", None)],
    )) == "5 new job matches, 1 application needs you, 2 follow-ups due"
    assert digest_subject(_digest(tailored_ready=2)) == "2 tailored applications to review"
    assert _digest().is_empty and digest_subject(_digest()) == "Nothing new today"


def test_email_links_to_the_app_and_escapes_job_text(monkeypatch):
    monkeypatch.setattr(digest_module, "frontend_url", lambda: "https://app.example")
    job_id, application_id = uuid.uuid4(), uuid.uuid4()
    subject, html, text = render_digest(_digest(
        new_match_count=7,
        top_matches=[DigestJob(job_id, "<script>alert(1)</script> Engineer", "Acme & Co", "Lagos", 81.6)],
        needs_you=[WaitingApplication(application_id, "AI Engineer", "Anthropic", 10)],
        tailored_ready=1,
        follow_ups=[FollowUp("Data Analyst", "Globex", None)],
    ), unsubscribe="https://api.example/api/v1/notifications/unsubscribe?u=1&t=abc")
    assert subject.startswith("7 new job matches")
    assert "<script>" not in html and "&lt;script&gt;" in html and "Acme &amp; Co" in html
    assert f"https://app.example/dashboard/jobs/{job_id}" in html
    assert f"https://app.example/dashboard/auto-apply/{application_id}" in html
    assert "10 questions to answer" in html and "See all in your inbox" in html
    assert "stop these emails" in html and "unsubscribe?u=1&amp;t=abc" in html
    assert ">82<" in html  # scores are rounded
    assert "82  <script>alert(1)</script> Engineer — Acme & Co · Lagos" in text
    assert "Stop these emails: https://api.example/api/v1/notifications/unsubscribe?u=1&t=abc" in text


def test_unsubscribe_tokens(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "s3cret")
    user = uuid.uuid4()
    token = unsubscribe_token(user)
    assert valid_unsubscribe_token(user, token)
    assert not valid_unsubscribe_token(uuid.uuid4(), token)
    assert not valid_unsubscribe_token(user, token[:-1] + "0")
    monkeypatch.setattr(get_settings(), "supabase_jwt_secret", "")
    assert not valid_unsubscribe_token(user, token)
