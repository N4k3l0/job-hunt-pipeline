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


async def test_matching_roles_past_a_big_boards_newest_30_still_count(monkeypatch):
    board = "https://job-boards.greenhouse.io/acme/jobs"
    monkeypatch.setattr(curated_service, "_load_companies",
                        lambda: [{"name": "Acme", "slug": "acme", "ats": "greenhouse"}])

    async def fetch(client, company):
        jobs = [{"title": f"Account Executive {i}", "job_url": f"{board}/{i}/", "raw_description": ""} for i in range(40)]
        return jobs + [{"title": "AI Automation Engineer", "job_url": f"{board}/99/", "raw_description": ""}]

    monkeypatch.setitem(curated_service._FETCHERS, "greenhouse", fetch)
    boards = await curated_service.fetch_board_listings(keywords={"automation"})
    assert [j["title"] for j in boards.jobs] == ["AI Automation Engineer"]
    assert len(boards.listed) == 41


def test_new_jobs_skip_known_ones_and_every_company_gets_a_turn():
    def board(name, n):
        return [{"company": name, "title": f"{name} job {i}", "job_url": f"https://jobs.example.com/{name}/{i}"}
                for i in range(n)]

    boards = [board("first", 40), board("second", 40), board("third", 2)]
    known = {"jobs.example.com/first/0", "jobs.example.com/first/1"}
    from app.services.parsing.normalizer import normalize_url
    known = {normalize_url(f"https://{k}") for k in known}

    picked = curated_service.pick_new_jobs(boards, known, limit=7)
    assert [j["title"] for j in picked] == [
        "first job 2", "second job 0", "third job 0",
        "first job 3", "second job 1", "third job 1",
        "first job 4",
    ]
    # Never more than the cap from one company.
    many = curated_service.pick_new_jobs(boards, limit=0)
    assert sum(j["company"] == "first" for j in many) == curated_service.PER_COMPANY_CAP


def test_only_titles_matching_someones_roles_or_skills_are_added():
    titles = curated_service.title_matcher(["AI Engineer", "Product Manager", "Python", "ai"])
    board = [{"title": t, "job_url": f"https://jobs.example.com/acme/{i}"} for i, t in enumerate([
        "Senior AI Engineer, Platform", "Account Executive", "Maintenance Technician",
        "Group Product Manager", "Python Developer", "AI Solutions Architect",
    ])]
    picked = curated_service.pick_new_jobs([board], titles=titles)
    assert [j["title"] for j in picked] == [
        "Senior AI Engineer, Platform", "Group Product Manager", "Python Developer", "AI Solutions Architect",
    ]
    assert curated_service.title_matcher([]) is None
