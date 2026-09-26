from app.services.discovery import curated_service


async def test_every_listing_counts_but_only_the_first_30_are_added(monkeypatch):
    board = "https://job-boards.greenhouse.io/anthropic/jobs"
    monkeypatch.setattr(curated_service, "_load_companies",
                        lambda: [{"name": "Anthropic", "slug": "anthropic", "ats": "greenhouse"}])

    async def fetch(client, company):
        return [{"title": f"Job {i}", "job_url": f"{board}/{i}/", "raw_description": ""} for i in range(40)]

    monkeypatch.setitem(curated_service._FETCHERS, "greenhouse", fetch)

    boards = await curated_service.fetch_board_listings()
    assert len(boards.jobs) == curated_service.PER_COMPANY_CAP == 30
    assert len(boards.listed) == 40
    assert boards.listed[f"{board}/39"] == "Job 39"  # past the cap, and normalized
    assert await curated_service.fetch_jobs() == boards.jobs
