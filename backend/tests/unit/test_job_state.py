import pytest

from app.services.job_state import effective_status


@pytest.mark.parametrize(
    "job_status, user_state, tracking_status, expected",
    [
        ("scored", None, None, "scored"),
        ("scored", "shortlisted", None, "shortlisted"),
        ("scored", "dismissed", None, "dismissed"),
        ("scored", "shortlisted", "applied", "applied"),
        ("scored", None, "interviewing", "applied"),
        # A tailored-but-not-applied tracking row doesn't count as applied.
        ("scored", "shortlisted", "approved", "shortlisted"),
        ("enriched", None, "approved", "enriched"),
    ],
)
def test_effective_status(job_status, user_state, tracking_status, expected):
    assert effective_status(job_status, user_state, tracking_status) == expected
