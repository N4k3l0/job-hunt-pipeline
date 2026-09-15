"""Cron endpoints refuse every request until their secret is set, so a
fresh deployment never exposes them."""

import pytest
from fastapi import HTTPException

from app.api.v1.cron import _verify_cron


def test_cron_rejects_everything_without_a_secret(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)
    for header in (None, "Bearer ", "Bearer anything"):
        with pytest.raises(HTTPException) as err:
            _verify_cron(header)
        assert err.value.status_code == 503


def test_cron_checks_the_secret(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    for header in (None, "s3cret", "Bearer wrong", "Bearer s3cret2"):
        with pytest.raises(HTTPException) as err:
            _verify_cron(header)
        assert err.value.status_code == 401
    _verify_cron("Bearer s3cret")

