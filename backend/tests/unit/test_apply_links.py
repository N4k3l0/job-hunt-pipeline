import httpx
import pytest

from app.services.auto_apply.apply_links import find_apply_url, has_apply_redirect
from app.services.auto_apply.ats import detect_ats, hiring_system_name

JOB = "https://www.arbeitnow.co.uk/jobs/companies/kraken/senior-solutions-engineer-london-84553"
ASHBY = ("https://jobs.ashbyhq.com/kraken.com/2727f6f7-31b2-4f8f-95d9-55cecde1f340/application"
         "?utm_source=arbeitnow.co.uk&ref=arbeitnow.co.uk")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_only_job_board_listings_have_an_apply_redirect():
    assert has_apply_redirect(JOB)
    assert has_apply_redirect("https://www.arbeitnow.com/jobs/companies/jimdo/senior-ai-engineer-germany-32291")
    assert has_apply_redirect("https://arbeitnow.fr/jobs/companies/nabla/ml-engineer-paris-198708")
    assert not has_apply_redirect("https://www.arbeitnow.com/jobs")
    assert not has_apply_redirect("https://job-boards.greenhouse.io/acme/jobs/111")
    assert not has_apply_redirect(None)


async def test_follows_the_apply_redirect_to_the_company_form():
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(str(request.url))
        return httpx.Response(302, headers={"location": ASHBY})

    async with _client(handler) as client:
        url = await find_apply_url(JOB + "?utm_source=feed", client)

    assert asked == [JOB + "/apply"]
    assert url == ASHBY
    target = detect_ats(url)
    assert (target.ats, target.board, target.job_id) == ("ashby", "kraken.com", "2727f6f7-31b2-4f8f-95d9-55cecde1f340")


@pytest.mark.parametrize("response", [
    httpx.Response(404),
    httpx.Response(200, text="<html>Apply</html>"),
    httpx.Response(302, headers={"location": "https://www.arbeitnow.co.uk/jobs"}),  # job gone
    httpx.Response(302, headers={"location": "/jobs"}),
])
async def test_listings_that_lead_nowhere(response):
    async with _client(lambda request: response) as client:
        assert await find_apply_url(JOB, client) is None


@pytest.mark.parametrize("status", [429, 503])
async def test_board_trouble_is_an_error_to_retry(status):
    async with _client(lambda request: httpx.Response(status)) as client:
        with pytest.raises(httpx.HTTPError):
            await find_apply_url(JOB, client)


async def test_other_links_are_not_requested():
    def handler(request):
        raise AssertionError("no request expected")

    async with _client(handler) as client:
        assert await find_apply_url("https://himalayas.app/companies/acme/jobs/ml-engineer", client) is None


@pytest.mark.parametrize("url, name", [
    ("https://join.com/companies/acme/1234-ai-engineer", "Join"),
    ("https://acme.jobs.personio.de/job/123", "Personio"),
    ("https://acme.recruitee.com/o/ai-engineer", "Recruitee"),
    ("https://acme.wd5.myworkdayjobs.com/en-US/External/job/London/AI-Engineer_R123", "Workday"),
    ("https://jobs.smartrecruiters.com/Acme/123", "SmartRecruiters"),
    ("https://careers.acme.com/jobs/123", None),
    (None, None),
])
def test_hiring_system_names(url, name):
    assert hiring_system_name(url) == name
