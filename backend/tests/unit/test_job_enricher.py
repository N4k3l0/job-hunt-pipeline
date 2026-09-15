from datetime import datetime, timezone

import pytest

from app.models.job import Job, JobEntity
from app.services.enrichment.job_enricher import annual_salary, apply_extraction, clean_description

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)


def _job(**kwargs):
    defaults = dict(title="Staff Accountant", company="Acme", seniority=None, employment_type=None,
                    remote_type=None, salary_min=None, salary_max=None, salary_currency=None)
    defaults.update(kwargs)
    return Job(**defaults)


def test_apply_extraction_fills_entity_and_missing_job_fields():
    job = _job()
    entity = JobEntity(skills=["Finance"], requirements=[], keywords=[])
    apply_extraction(job, entity, {
        "required_skills": ["IFRS", "Excel", "excel", "  "],
        "nice_to_have_skills": ["SAP"],
        "requirements": ["Own month-end close"],
        "keywords": ["fintech"],
        "seniority": "mid",
        "years_experience_min": 3,
        "employment_type": "full_time",
        "remote_type": "hybrid",
        "eligible_countries": ["gb", "IE", "WW", "Germany"],
        "sponsorship_available": False,
        "visa_notes": "No sponsorship.",
        "salary_min": 45000,
        "salary_max": 55000,
        "salary_currency": "gbp",
    }, NOW)

    assert entity.skills == ["IFRS", "Excel"]
    assert entity.nice_to_have == ["SAP"]
    assert entity.requirements == ["Own month-end close"]
    assert entity.keywords == ["fintech"]
    assert entity.years_experience_min == 3
    assert entity.eligible_countries == ["GB", "IE"]
    assert entity.sponsorship_available is False
    assert entity.visa_notes == "No sponsorship."
    assert entity.enriched_at == NOW
    assert (job.seniority, job.employment_type, job.remote_type) == ("mid", "full_time", "hybrid")
    assert (job.salary_min, job.salary_max, job.salary_currency) == (45000, 55000, "GBP")


def test_source_values_on_the_job_are_not_overwritten():
    job = _job(seniority="senior", remote_type="full_remote", salary_min=90000, salary_max=None,
               salary_currency="USD")
    entity = JobEntity(skills=["Tag"], requirements=[], keywords=[], sponsorship_available=True,
                       eligible_countries=["US"])
    apply_extraction(job, entity, {
        "required_skills": [],
        "nice_to_have_skills": [],
        "requirements": [],
        "keywords": [],
        "seniority": "entry",
        "remote_type": "onsite",
        "eligible_countries": [],
        "sponsorship_available": False,
        "salary_min": 10,
        "salary_max": 20,
    }, NOW)

    assert (job.seniority, job.remote_type) == ("senior", "full_remote")
    assert (job.salary_min, job.salary_max) == (90000, None)
    # An empty extraction keeps the source's tags and restriction.
    assert entity.skills == ["Tag"]
    assert entity.eligible_countries == ["US"]
    assert entity.sponsorship_available is True


def test_invalid_values_are_ignored():
    job = _job()
    entity = JobEntity(skills=[], requirements=[], keywords=[])
    apply_extraction(job, entity, {
        "required_skills": "not a list",
        "nice_to_have_skills": None,
        "requirements": [],
        "keywords": [],
        "seniority": "wizard",
        "years_experience_min": -2,
        "salary_min": True,
        "eligible_countries": "US",
    }, NOW)
    assert job.seniority is None
    assert entity.years_experience_min is None
    assert job.salary_min is None
    assert entity.eligible_countries is None


def test_enum_values_wrapped_in_lists_are_accepted():
    # Seen from Claude Haiku 4.5 on real postings: seniority: ["entry", "mid"].
    job = _job()
    entity = JobEntity(skills=[], requirements=[], keywords=[])
    apply_extraction(job, entity, {
        "required_skills": [], "nice_to_have_skills": [], "requirements": [], "keywords": [],
        "seniority": ["entry", "mid"], "employment_type": ["full_time"], "remote_type": ["full_remote"],
        "eligible_countries": [],
    }, NOW)
    assert (job.seniority, job.employment_type, job.remote_type) == ("entry", "full_time", "full_remote")


@pytest.mark.parametrize(
    "amount, period, expected",
    [
        (25, "hour", 52000),
        (4000, "month", 48000),
        (60000, "year", 60000),
        (60000, None, 60000),
        (50, None, None),       # per-article or hourly without a period: not a salary
        (0, "year", None),
        (None, "year", None),
        (30, ["hour"], 62400),
    ],
)
def test_annual_salary(amount, period, expected):
    assert annual_salary(amount, period) == expected


def test_clean_description_strips_html():
    assert clean_description("<p>Hello&nbsp;<b>there</b></p>\n\n  friend") == "Hello there friend"


def test_clean_description_decodes_escaped_html():
    escaped = '&lt;div class=&quot;intro&quot;&gt;&lt;p&gt;Grafana Labs &amp;amp; friends&#39; tools&lt;/p&gt;&lt;/div&gt;'
    assert clean_description(escaped) == "Grafana Labs & friends' tools"
    assert clean_description("&amp;lt;p&amp;gt;Twice&amp;lt;/p&amp;gt;") == "Twice"
    assert clean_description("Salary: 5 < 6 and R&D") == "Salary: 5 < 6 and R&D"


def test_implausible_salary_ranges_are_dropped():
    # Seen on a real posting: one run returned 100 to 45,000 per year.
    job = _job()
    entity = JobEntity(skills=[], requirements=[], keywords=[])
    apply_extraction(job, entity, {
        "required_skills": [], "nice_to_have_skills": [], "requirements": [], "keywords": [],
        "eligible_countries": [], "salary_min": 1500, "salary_max": 45000, "salary_period": "year",
    }, NOW)
    assert (job.salary_min, job.salary_max) == (None, None)
