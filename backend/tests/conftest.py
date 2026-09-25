"""Test environment.

Settings are read when app modules are imported, so the environment is
set here before any test imports them. Unit tests never touch a
database. Integration tests run only when TEST_DATABASE_URL points at a
disposable Postgres (with pgvector) whose database name contains "test":

    TEST_DATABASE_URL=postgresql://postgres@localhost:5432/jobhunt_test pytest
"""

import os

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

os.environ["DATABASE_URL"] = TEST_DATABASE_URL or "postgresql://unused:unused@localhost:1/unused"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["VOYAGE_API_KEY"] = ""
os.environ["ENVIRONMENT"] = "test"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _ai_not_paused(monkeypatch, tmp_path):
    """Each test gets its own AI pause file, so a test that runs out of
    credits can't pause AI for another test or on the machine."""
    from app.llm import client as llm_module

    monkeypatch.setattr(llm_module, "PAUSE_FILE", tmp_path / "ai-paused-until")
    monkeypatch.setattr(llm_module, "_credits_paused_until", 0.0)
