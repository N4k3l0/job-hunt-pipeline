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
