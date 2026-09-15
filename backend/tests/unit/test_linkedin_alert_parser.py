from app.services.job_alerts.ingest import country_from_location
from app.services.job_alerts.linkedin import parse_linkedin_alert, parse_salary
from tests.linkedin_alert_email import alert_email_html


def test_every_job_in_the_email_is_read():
    parsed = parse_linkedin_alert(alert_email_html())
    assert parsed.search == "Automation Engineer"
    assert parsed.location == "United States"
    assert [(j.linkedin_job_id, j.position, j.list_name) for j in parsed.jobs] == [
        ("4100000001", 0, "primary_job_list"),
        ("4100000002", 1, "primary_job_list"),
        ("4100000003", 2, "primary_job_list"),
        ("4100000004", 3, "primary_job_list"),
    ]
    first, second, third, fourth = parsed.jobs
    assert (first.title, first.company, first.location, first.remote_type) == (
        "AI Automation Specialist", "Acme Talent", "United States", "full_remote",
    )
    assert (second.salary_text, second.salary_min, second.salary_max, second.salary_currency) == (
        "$74K-$76K / year", 74000, 76000, "USD",
    )
    assert second.remote_type == "onsite" and second.labels == ["Easy Apply"]
    assert (third.location, third.remote_type, third.salary_min, third.salary_currency) == ("Toronto, ON", "hybrid", 90000, "CAD")
    assert third.labels == ["Actively recruiting"]
    assert (fourth.location, fourth.remote_type, fourth.salary_text, fourth.labels) == (
        "London, England, United Kingdom", None, None, ["3 school alumni"],
    )
    # Links are LinkedIn's plain job page, without the email's sign-in codes.
    assert first.url == "https://www.linkedin.com/jobs/view/4100000001"


def test_links_without_tracking_still_give_every_job():
    # The Gmail script removes query strings except `trk`; with no `trk` at
    # all the jobs keep their order.
    body = alert_email_html().replace("trk=eml-email_job_alert_digest_01-primary_job_list", "trk=other")
    parsed = parse_linkedin_alert(body)
    assert [(j.linkedin_job_id, j.position, j.list_name) for j in parsed.jobs][:2] == [
        ("4100000001", 0, None), ("4100000002", 1, None),
    ]
    assert parsed.jobs[1].company == "Sunny Staffing"


def test_an_email_without_jobs():
    parsed = parse_linkedin_alert("<html><body>Your saved search has no new jobs</body></html>")
    assert parsed.jobs == []


def test_salaries():
    assert parse_salary("$74K-$76K / year") == (74000, 76000, "USD")
    assert parse_salary("£45,000 / yr") == (45000, None, "GBP")
    assert parse_salary("€30 - €40 / hour") == (62400, 83200, "EUR")
    assert parse_salary("₦1.5M / month") == (18000000, None, "NGN")
    assert parse_salary("Easy Apply") is None


def test_country_from_linkedin_locations():
    assert country_from_location("United States") == "US"
    assert country_from_location("Coral Gables, FL") == "US"
    assert country_from_location("Toronto, ON") == "CA"
    assert country_from_location("London, England, United Kingdom") == "GB"
    assert country_from_location("EMEA") is None
