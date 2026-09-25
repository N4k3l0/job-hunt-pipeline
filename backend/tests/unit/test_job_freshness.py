from datetime import datetime, timedelta, timezone

from app.models.job import Job
from app.services.job_freshness import closed_note

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def _job(found_days_ago, seen_days_ago=None):
    return Job(
        title="AI Engineer", company="Acme",
        discovered_at=NOW - timedelta(days=found_days_ago),
        last_seen_at=NOW - timedelta(days=seen_days_ago) if seen_days_ago is not None else None,
    )


def test_listed_recently_is_not_flagged():
    assert closed_note(_job(120, seen_days_ago=0), NOW) is None
    assert closed_note(_job(120, seen_days_ago=20), NOW) is None


def test_not_listed_for_three_weeks_is_flagged_with_the_date():
    assert closed_note(_job(120, seen_days_ago=25), NOW) == (
        "This job may have closed. The app last saw it listed on 31 August."
    )


def test_never_seen_again_counts_from_when_it_was_found():
    assert closed_note(_job(143), NOW) == "This job may have closed. The app last saw it listed on 5 May."
    assert closed_note(_job(10), NOW) is None
