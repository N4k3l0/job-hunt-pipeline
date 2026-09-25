"""Fetching job board pages: directly first, Firecrawl only as a fallback,
and Firecrawl left alone for a while once it says "too many requests"."""

import httpx
import pytest

from app.services.discovery import firecrawl_service as fetch
from app.services.discovery.jobposting import job_posting

LISTING = "<html><body><h1>Jobs</h1>" + "".join(
    f'<p><a href="/job/role-{i}">Role {i}</a></p>' for i in range(60)
) + "<script>var x = 'ignored';</script></body></html>"


@pytest.fixture
def web(monkeypatch):
    """A fake internet: `sites` answers direct requests, `firecrawl` answers
    the Firecrawl API. Records every request."""
    state = {"sites": {}, "firecrawl": None, "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(str(request.url))
        if request.url.host == "api.firecrawl.dev":
            return state["firecrawl"](request)
        status, body = state["sites"].get(str(request.url), (404, "gone"))
        return httpx.Response(status, text=body)

    real_client = httpx.AsyncClient

    class Client(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(fetch.httpx, "AsyncClient", Client)
    monkeypatch.setattr(fetch.settings, "firecrawl_api_key", "fc-test")
    monkeypatch.setattr(fetch, "_firecrawl_paused_until", 0.0)
    return state


async def test_a_page_that_answers_is_read_directly(web):
    web["sites"]["https://board.test/jobs"] = (200, LISTING)
    web["firecrawl"] = lambda request: pytest.fail("Firecrawl shouldn't be asked")

    markdown = await fetch.scrape_url("https://board.test/jobs")
    # Links come out absolute, the way the source parsers expect them.
    assert "[Role 3](https://board.test/job/role-3)" in markdown
    assert "ignored" not in markdown
    assert web["requests"] == ["https://board.test/jobs"]


async def test_firecrawl_is_the_fallback_and_rests_after_too_many_requests(web):
    web["sites"]["https://blocked.test/jobs"] = (403, "no")
    calls = {"n": 0}

    def firecrawl(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"data": {"markdown": "# Jobs\n[A](https://blocked.test/job/a)"}})
        return httpx.Response(429, json={"error": "rate limited"})

    web["firecrawl"] = firecrawl
    assert "[A]" in await fetch.scrape_url("https://blocked.test/jobs")

    # Out of credits: the next page fails, and Firecrawl isn't asked again.
    with pytest.raises(ValueError):
        await fetch.scrape_url("https://blocked.test/jobs")
    assert await fetch.scrape_html("https://blocked.test/jobs") == ""
    assert calls["n"] == 2


async def test_without_a_firecrawl_key_a_blocked_page_is_just_skipped(web, monkeypatch):
    monkeypatch.setattr(fetch.settings, "firecrawl_api_key", "")
    web["sites"]["https://blocked.test/jobs"] = (403, "no")
    web["firecrawl"] = lambda request: pytest.fail("no key, no Firecrawl")
    assert await fetch.scrape_html("https://blocked.test/jobs") == ""


def test_the_pages_own_job_record_names_the_company_and_place():
    html = """<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [
      {"@type": "BreadcrumbList"},
      {"@type": "JobPosting", "title": "AI Engineer", "datePosted": "2026-09-16",
       "hiringOrganization": {"@type": "Organization", "name": "Redule Ai"},
       "jobLocation": [{"@type": "Place", "address": {"addressRegion": "Dubai",
                        "addressCountry": "United Arab Emirates"}}]}]}</script>"""
    assert job_posting(html) == {"title": "AI Engineer", "company": "Redule Ai",
                                 "location": "Dubai, United Arab Emirates", "date_posted": "2026-09-16"}
    assert job_posting("<html>no record</html>") is None
    assert job_posting('<script type="application/ld+json">{not json</script>') is None


def test_myjobmag_titles_name_the_company():
    from app.services.discovery.myjobmag_service import _parse_detail

    markdown = "# Finance officer at First Ally Trust MFB\n\n" + "About the role. " * 30
    job = _parse_detail(title="Finance officer", url="https://www.myjobmag.com/job/finance-officer", markdown=markdown)
    assert job["title"] == "Finance officer"
    assert job["company"] == "First Ally Trust MFB"
