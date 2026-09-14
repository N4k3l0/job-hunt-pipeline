"""The scheduler runs discovery once a day in two halves and everything
else on every run."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

_path = Path(__file__).parents[2] / "scripts" / "scheduled_tasks.py"
_spec = importlib.util.spec_from_file_location("scheduled_tasks", _path)
scheduled_tasks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scheduled_tasks)


def at(hour, minute):
    return datetime(2026, 9, 15, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize("now, expected", [
    (at(6, 0), ["fast"]),
    (at(6, 4), ["fast"]),   # Railway can start a run a few minutes late
    (at(6, 30), ["remote"]),
    (at(6, 33), ["remote"]),
    (at(5, 30), []),
    (at(7, 0), []),
    (at(18, 30), []),
])
def test_discovery_due(now, expected):
    assert scheduled_tasks.discovery_due(now) == expected


def test_run_calls_endpoints_in_order(monkeypatch):
    calls = []

    def fake_call(base_url, secret, path, timeout):
        calls.append((base_url, path))
        return not path.startswith("/api/v1/cron/expire-stale")

    monkeypatch.setattr(scheduled_tasks, "call", fake_call)
    monkeypatch.setenv("BACKEND_URL", "backend.example.app")
    monkeypatch.setenv("CRON_SECRET", "s")
    monkeypatch.setenv("ENRICH_JOBS_PER_RUN", "40")
    monkeypatch.setenv("REVIEWS_PER_USER_PER_DAY", "2")
    monkeypatch.setattr("sys.argv", ["scheduled_tasks.py", "--discovery", "both"])

    assert scheduled_tasks.main() == 1  # expire-stale failed
    assert calls == [
        ("https://backend.example.app", "/api/v1/cron/discover-fast"),
        ("https://backend.example.app", "/api/v1/cron/discover-remote"),
        ("https://backend.example.app", "/api/v1/cron/enrich?limit=40"),
        ("https://backend.example.app", "/api/v1/cron/expire-stale?verify_limit=40"),
        ("https://backend.example.app", "/api/v1/cron/review-top-matches?per_user_daily=2"),
    ]


def test_missing_settings(monkeypatch):
    monkeypatch.delenv("BACKEND_URL", raising=False)
    monkeypatch.setenv("CRON_SECRET", "s")
    monkeypatch.setattr("sys.argv", ["scheduled_tasks.py"])
    assert scheduled_tasks.main() == 2
