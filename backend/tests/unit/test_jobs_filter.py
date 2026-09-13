import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models.job import Job, JobSource
from app.services.jobs_filter import apply_user_filters, country_filter_codes


def _sql(query) -> str:
    return str(query.compile(dialect=postgresql.dialect()))


def _base():
    return select(Job.id).outerjoin(JobSource, JobSource.id == Job.source_id)


@pytest.mark.parametrize(
    "prefs, expected",
    [
        (None, None),
        ([], None),
        (["WW"], None),
        (["ww"], None),
        (["NL", "WW"], None),
        (["nl", " de "], ["NL", "DE"]),
    ],
)
def test_country_filter_codes(prefs, expected):
    assert country_filter_codes(prefs) == expected


def test_worldwide_adds_no_location_filter():
    worldwide = _sql(apply_user_filters(_base(), target_roles=None, preferred_countries=["WW"]))
    unfiltered = _sql(apply_user_filters(_base(), target_roles=None, preferred_countries=None))
    assert worldwide == unfiltered
    assert "country" not in worldwide
    assert "~*" not in worldwide


def test_real_countries_add_location_filter():
    sql = _sql(apply_user_filters(_base(), target_roles=None, preferred_countries=["NL"]))
    assert "upper(jobs.country) IN" in sql
    assert "~*" in sql


def test_target_roles_filter_titles():
    sql = _sql(apply_user_filters(_base(), target_roles=["Product Manager"]))
    assert "lower(jobs.title) LIKE" in sql
