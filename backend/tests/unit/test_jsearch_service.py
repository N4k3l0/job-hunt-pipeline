import asyncio
import time

import httpx

from app.services.discovery import jsearch_service


def _result(query: str, n: int) -> dict:
    return {"job_id": f"{query}-{n}", "employer_name": "Acme", "job_title": f"{query} {n}",
            "job_apply_link": f"https://jobs.example/{query}/{n}"}


async def test_searches_run_together_and_a_slow_one_is_dropped(monkeypatch):
    monkeypatch.setattr(jsearch_service.settings, "jsearch_rapidapi_key", "test-key")
    asked = []

    async def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        asked.append((query, request.url.params["page"]))
        await asyncio.sleep(5 if query == "slow" else 0.2)
        return httpx.Response(200, json={"data": [_result(query, 1), _result(query, 2)]})

    started = time.monotonic()
    jobs = await jsearch_service.fetch_jobs(
        queries=["ai engineer", "slow", "ml engineer"], deadline_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )
    elapsed = time.monotonic() - started

    assert elapsed < 2  # together, not one after another, and the slow one isn't waited for
    assert sorted(j["title"] for j in jobs) == ["ai engineer 1", "ai engineer 2", "ml engineer 1", "ml engineer 2"]
    assert sorted(asked) == [("ai engineer", "1"), ("ml engineer", "1"), ("slow", "1")]  # one page each


async def test_an_error_on_one_search_keeps_the_others(monkeypatch):
    monkeypatch.setattr(jsearch_service.settings, "jsearch_rapidapi_key", "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"] == "broken":
            return httpx.Response(429)
        return httpx.Response(200, json={"data": [_result("ok", 1)]})

    jobs = await jsearch_service.fetch_jobs(queries=["broken", "fine"], transport=httpx.MockTransport(handler))
    assert [j["title"] for j in jobs] == ["ok 1"]
