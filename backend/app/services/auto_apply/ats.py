"""Work out which hiring system hosts a job's application form.

Supported: Greenhouse, Lever and Ashby. Each publishes a job's application
questions without a login, which is what lets the app prepare answers.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.services.discovery.ats_resolver import _slug_candidates

SUPPORTED_ATS = ("greenhouse", "lever", "ashby")

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_GREENHOUSE_HOST = re.compile(r"^(?:job-boards|boards)(\.eu)?\.greenhouse\.io$")
_LEVER_HOST = re.compile(r"^jobs(\.eu)?\.lever\.co$")


@dataclass(frozen=True)
class AtsTarget:
    ats: str
    board: str | None  # company's board name; None when only the job id is known
    job_id: str
    eu: bool = False

    @property
    def form_url(self) -> str | None:
        """The page where a person fills in the application."""
        if self.board is None:
            return None
        if self.ats == "greenhouse":
            host = "job-boards.eu.greenhouse.io" if self.eu else "job-boards.greenhouse.io"
            return f"https://{host}/{self.board}/jobs/{self.job_id}"
        if self.ats == "lever":
            host = "jobs.eu.lever.co" if self.eu else "jobs.lever.co"
            return f"https://{host}/{self.board}/{self.job_id}/apply"
        return f"https://jobs.ashbyhq.com/{self.board}/{self.job_id}/application"


def detect_ats(url: str | None) -> AtsTarget | None:
    """Recognise a Greenhouse, Lever or Ashby job from its URL, without
    any network calls. Company career sites that embed Greenhouse
    (`?gh_jid=123`) give the job id but not the board name."""
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)

    gh = _GREENHOUSE_HOST.match(host)
    if gh:
        eu = bool(gh.group(1))
        if parts[:1] == ["embed"]:
            board, token = (query.get("for") or [None])[0], (query.get("token") or [None])[0]
            if board and token and token.isdigit():
                return AtsTarget("greenhouse", board, token, eu)
            return None
        if len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
            return AtsTarget("greenhouse", parts[0], parts[2], eu)
        return None

    lever = _LEVER_HOST.match(host)
    if lever:
        if len(parts) >= 2 and re.fullmatch(_UUID, parts[1].lower()):
            return AtsTarget("lever", parts[0], parts[1].lower(), bool(lever.group(1)))
        return None

    if host == "jobs.ashbyhq.com":
        if len(parts) >= 2 and re.fullmatch(_UUID, parts[1].lower()):
            return AtsTarget("ashby", parts[0], parts[1].lower())
        return None

    gh_jid = (query.get("gh_jid") or [None])[0]
    if gh_jid and gh_jid.isdigit():
        return AtsTarget("greenhouse", None, gh_jid)
    return None


@lru_cache(maxsize=1)
def _curated_greenhouse_boards() -> dict[str, str]:
    path = Path(__file__).parents[1] / "discovery" / "curated_companies.json"
    with open(path) as f:
        companies = (json.load(f) or {}).get("companies") or []
    return {c["name"].strip().lower(): c["slug"] for c in companies if c.get("ats") == "greenhouse"}


async def resolve_greenhouse_board(client: httpx.AsyncClient, company: str, job_id: str) -> str | None:
    """Find the board name for a Greenhouse job known only by its id, by
    checking which of the company's likely board names lists that job."""
    candidates: list[str] = []
    curated = _curated_greenhouse_boards().get((company or "").strip().lower())
    if curated:
        candidates.append(curated)
    candidates += [s for s in _slug_candidates(company or "") if s not in candidates]
    for board in candidates[:5]:
        try:
            r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
        except httpx.HTTPError:
            continue
        if r.status_code == 200:
            return board
    return None
