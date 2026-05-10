"""Resolve a (company, title) pair to its direct ATS URL.

Why server-side and not Google? Search engines (Google, Bing, DDG) all
block scrapes from serverless IPs, and even when they respond, the result
HTML is JavaScript-rendered. Instead we go straight to the source: every
major free ATS publishes a public, no-auth JSON API listing the jobs on a
given company's board. We:

  1. Slugify the company name a few ways (anthropic, anthropic-inc, etc.)
  2. Try each slug against Greenhouse → Lever → Ashby in order
  3. On a 200 response, search the returned jobs for a title match
  4. Return the canonical posting URL (or the board URL if no title match)

Result: one click → company's actual posting page, no signup wall.

Limitations: only works for companies that use one of the three big
free ATSes. About 60-70% of remote-friendly tech postings do; for the
rest the caller falls back to the original aggregator URL.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "JobHuntPipeline/1.0"
TIMEOUT = httpx.Timeout(connect=3.0, read=4.0, write=3.0, pool=3.0)

# Hosts we recognise as "already an ATS direct link" — caller can skip
# resolution entirely if the source URL is already on one of these.
ATS_HOSTS: tuple[str, ...] = (
    "boards.greenhouse.io", "job-boards.greenhouse.io",
    "jobs.lever.co", "jobs.ashbyhq.com",
    "apply.workable.com", "jobs.workable.com",
    "jobs.smartrecruiters.com", "jobs.jobvite.com",
    "recruitee.com", "bamboohr.com", "breezy.hr",
    "myworkdayjobs.com", "teamtailor.com",
    "icims.com", "pinpointhq.com",
)


def is_ats_url(url: str | None) -> bool:
    """Cheap host-suffix check — caller can short-circuit resolution."""
    if not url:
        return False
    try:
        host = httpx.URL(url).host or ""
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in ATS_HOSTS)


def _slug_candidates(company: str) -> list[str]:
    """Generate plausible ATS slugs from a free-text company name.

    Real-world variants we've seen:
      "Anthropic"           → ["anthropic"]
      "OpenAI, Inc."        → ["openai-inc", "openai"]
      "Y Combinator"        → ["y-combinator", "ycombinator", "ycomb"]
      "Stripe"              → ["stripe"]
    We try the most likely first; the resolver stops on the first 200.
    """
    base = company.strip().lower()
    # Strip common corporate suffixes
    base = re.sub(r"\b(inc|llc|ltd|gmbh|co|corp|corporation|company)\.?\b", "", base)
    base = re.sub(r"[,\.]+", " ", base)
    base = base.strip()
    words = [w for w in re.split(r"\s+", base) if w]

    out: list[str] = []
    if not words:
        return out
    # full slug ("y-combinator")
    out.append("-".join(words))
    # squashed slug ("ycombinator")
    out.append("".join(words))
    # first word only ("y")
    if len(words) > 1:
        out.append(words[0])
    # alphanumeric-only of full
    cleaned = re.sub(r"[^a-z0-9]", "", "-".join(words))
    if cleaned and cleaned not in out:
        out.append(cleaned)

    # Dedupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for s in out:
        if s and s not in seen and len(s) >= 2:
            seen.add(s)
            deduped.append(s)
    return deduped


def _title_match(needle: str, haystack: str) -> bool:
    """Loose title equality. The aggregator title and the ATS title
    rarely match exactly — the aggregator may add a location ("Remote"),
    a level ("Senior"), or a department ("@ AI Platform").

    Bidirectional 70% rule: a match counts if EITHER side covers ≥70% of
    its tokens with the intersection. This handles asymmetric cases like:
        "Senior Product Manager, AI Platform"  vs  "Product Manager"
        {product, manager, ai, platform}      ∩  {product, manager}
        coverage of needle = 2/4 = 50%   ← old threshold misses
        coverage of haystack = 2/2 = 100% ← matches under the new rule
    """
    if not needle or not haystack:
        return False
    stop = {"a", "the", "of", "and", "for", "to", "in", "at", "on",
            "remote", "hybrid", "us", "uk", "eu", "global", "anywhere",
            "senior", "sr", "junior", "jr", "lead", "principal", "staff"}

    def tokens(s: str) -> set[str]:
        return {t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in stop}

    a, b = tokens(needle), tokens(haystack)
    if not a or not b:
        return False
    common = len(a & b)
    return common / len(a) >= 0.7 or common / len(b) >= 0.7


# ─── Per-ATS probes ─────────────────────────────────────────────────────────

async def _try_greenhouse(client: httpx.AsyncClient, slug: str, title: str) -> str | None:
    """Greenhouse: GET /v1/boards/<slug>/jobs returns JSON {jobs: [{title, absolute_url}]}.

    Only returns a URL when we can pin the EXACT job. If the company is on
    Greenhouse but the title doesn't match anything on their board (the role
    was filled, the title differs too much, etc.) we return None and let the
    caller fall back to the original aggregator URL — landing on a list of
    unrelated jobs is a worse experience than landing on the source posting.
    """
    try:
        r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if r.status_code != 200:
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    for j in data.get("jobs") or []:
        if _title_match(title, j.get("title") or ""):
            return j.get("absolute_url")
    return None


async def _try_lever(client: httpx.AsyncClient, slug: str, title: str) -> str | None:
    """Lever: GET /v0/postings/<slug>?mode=json returns a JSON array."""
    try:
        r = await client.get(
            f"https://api.lever.co/v0/postings/{slug}",
            params={"mode": "json"},
        )
        if r.status_code != 200:
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    for j in data:
        if _title_match(title, j.get("text") or ""):
            return j.get("hostedUrl") or j.get("applyUrl")
    return None  # company on Lever but title didn't match — let caller fall back


async def _try_ashby(client: httpx.AsyncClient, slug: str, title: str) -> str | None:
    """Ashby: GET /posting-api/job-board/<slug> returns JSON {jobs: [{title, jobUrl}]}."""
    try:
        r = await client.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        )
        if r.status_code != 200:
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    for j in data.get("jobs") or []:
        if _title_match(title, j.get("title") or ""):
            return j.get("jobUrl") or j.get("applyUrl")
    return None  # company on Ashby but title didn't match — let caller fall back


async def _try_personio(client: httpx.AsyncClient, slug: str, title: str) -> str | None:
    """Personio: GET https://<slug>.jobs.personio.com/xml returns an XML feed
    of `<position>` elements (id, name, recruitingCategory, ...). Used by a
    lot of European employers (Celonis, Personio itself, etc.).
    """
    try:
        r = await client.get(f"https://{slug}.jobs.personio.com/xml")
        if r.status_code != 200 or not r.text:
            return None
        body = r.text
    except httpx.HTTPError:
        return None

    # Lightweight parse — avoid xml.etree because some feeds embed CDATA
    # with malformed HTML that trips strict parsers.
    positions = re.findall(
        r"<position>(.*?)</position>", body, re.S | re.I,
    )
    for pos in positions:
        m_name = re.search(r"<name>(.*?)</name>", pos, re.S | re.I)
        m_id = re.search(r"<id>(.*?)</id>", pos, re.S | re.I)
        if not m_name or not m_id:
            continue
        name = re.sub(r"<.*?>", "", m_name.group(1)).strip()
        if _title_match(title, name):
            return f"https://{slug}.jobs.personio.com/job/{m_id.group(1).strip()}"
    return None


async def _try_smartrecruiters(client: httpx.AsyncClient, slug: str, title: str) -> str | None:
    """SmartRecruiters: GET /v1/companies/<slug>/postings returns {content: [...]}.

    SmartRecruiters slugs are case-sensitive and often Title-cased (e.g.
    "Bosch", "PublicisGroup"). We try the slug as-is and a lowercase variant.
    """
    for variant in (slug, slug.title(), slug.upper()):
        try:
            r = await client.get(
                f"https://api.smartrecruiters.com/v1/companies/{variant}/postings",
                params={"limit": 100},
            )
            if r.status_code != 200:
                continue
            data = r.json()
        except (httpx.HTTPError, ValueError):
            continue
        for j in data.get("content") or []:
            if _title_match(title, j.get("name") or ""):
                # The "ref" link is the public posting URL.
                refs = j.get("ref")
                if isinstance(refs, str):
                    return refs
                # Sometimes nested: postUrl / applyUrl
                for k in ("postUrl", "applyUrl"):
                    if j.get(k):
                        return j[k]
        # Company on SmartRecruiters but title didn't match — try next slug
        # variant rather than returning a board URL the user can't act on.
    return None


# ─── Public API ─────────────────────────────────────────────────────────────

_ATS_URL_RE = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?"
    r"(?:greenhouse\.io|lever\.co|ashbyhq\.com|workable\.com|"
    r"smartrecruiters\.com|jobvite\.com|recruitee\.com|"
    r"bamboohr\.com|breezy\.hr|myworkdayjobs\.com|teamtailor\.com|"
    r"icims\.com|pinpointhq\.com|personio\.com)"
    r"/[^\s\"'<>&]+",
    re.I,
)


async def follow_to_ats(client: httpx.AsyncClient, source_url: str) -> str | None:
    """Try two cheap signals before any slug-guessing:

      1. Final URL after redirects — many aggregators 30x to the ATS for free.
      2. Failing that, scan the response BODY for any embedded ATS URL.
         Most aggregator postings have an 'Apply' anchor that points
         directly to the company's Greenhouse/Lever/Ashby page even when
         they don't redirect to it. Pulling that link out is the highest-
         leverage signal we have, because it's the URL the source already
         knew was canonical.
    """
    if not source_url:
        return None
    try:
        r = await client.get(source_url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        })
    except httpx.HTTPError:
        return None

    # 1. Final URL after redirects
    final = str(r.url)
    if is_ats_url(final):
        logger.info("Follow-redirect resolved %s → %s", source_url, final)
        return final

    # 2. Scan the body for embedded ATS URLs. Strip query strings / fragments
    #    that are sometimes added for tracking, then return the first match
    #    that looks like an actual posting URL (has a path beyond the host).
    body = r.text or ""
    for m in _ATS_URL_RE.finditer(body):
        candidate = m.group(0)
        # Filter out generic landing pages — we want a posting URL, not
        # the ATS provider's own marketing page (e.g. greenhouse.io itself).
        try:
            host = httpx.URL(candidate).host or ""
            path = httpx.URL(candidate).path or ""
        except Exception:
            continue
        if host in ("greenhouse.io", "lever.co", "workable.com",
                    "ashbyhq.com", "smartrecruiters.com", "personio.com"):
            # Bare provider domain, not a customer subdomain → skip
            continue
        if not path or path == "/":
            continue
        logger.info("Body-scan resolved %s → %s", source_url, candidate)
        return candidate
    return None


async def resolve_ats_url(company: str, title: str) -> str | None:
    """Best-effort: return the direct ATS URL for this (company, title), or None.

    Returns the most specific URL we can find:
      - Posting URL if the title matches one on the company's board
      - Board URL if the company is on the ATS but no title match
      - None if the company isn't on any of the three free ATSes we try

    Probes run priority-ordered (Greenhouse → Lever → Ashby) but slugs are
    tried concurrently within each probe — most companies are on exactly one
    ATS, so we stop the moment any probe hits, keeping worst case ≈ 12s.
    """
    if not company or not title:
        return None
    slugs = _slug_candidates(company)
    if not slugs:
        return None

    async def probe_all_slugs(client, probe):
        """Fire one probe across every candidate slug concurrently. First
        non-None result wins; pending tasks are cancelled."""
        tasks = [asyncio.create_task(probe(client, s, title)) for s in slugs]
        try:
            for fut in asyncio.as_completed(tasks):
                hit = await fut
                if hit:
                    return hit
            return None
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    ) as client:
        probes = (_try_greenhouse, _try_lever, _try_ashby,
                  _try_smartrecruiters, _try_personio)
        for probe in probes:
            hit = await probe_all_slugs(client, probe)
            if hit:
                logger.info(
                    "ATS resolver hit: %s '%s' → %s",
                    company, title, hit,
                )
                return hit
    return None


# Aggregators whose pages either gate the apply link behind paywall/JS
# UX (WeWorkRemotely's notification upsell) or block plain-httpx GETs
# entirely. For these we fall back to Firecrawl, which renders JS and
# returns the underlying ATS link that's actually on the page.
_FIRECRAWL_FALLBACK_HOSTS: tuple[str, ...] = (
    "weworkremotely.com",
    "dailyremote.com",
    "remotive.com",
    "remoteok.com",
    "himalayas.app",
)


def _needs_firecrawl(url: str) -> bool:
    try:
        host = httpx.URL(url).host or ""
    except Exception:
        return False
    return any(host == h or host.endswith("." + h) for h in _FIRECRAWL_FALLBACK_HOSTS)


async def follow_to_ats_via_firecrawl(source_url: str) -> str | None:
    """Same body-scan as follow_to_ats, but the page comes from Firecrawl
    so JS-rendered DOM and anti-bot paywalls don't hide the apply link.

    Used as a slow-path fallback when the cheap httpx GET returns nothing
    on a known-difficult aggregator (WeWorkRemotely's '$5/mo to see this'
    upsell, Cloudflare on DailyRemote, etc.).
    """
    from app.services.discovery.firecrawl_service import scrape_html

    body = await scrape_html(source_url, timeout=25.0)
    if not body:
        return None

    for m in _ATS_URL_RE.finditer(body):
        candidate = m.group(0)
        try:
            host = httpx.URL(candidate).host or ""
            path = httpx.URL(candidate).path or ""
        except Exception:
            continue
        if host in ("greenhouse.io", "lever.co", "workable.com",
                    "ashbyhq.com", "smartrecruiters.com", "personio.com"):
            continue
        if not path or path == "/":
            continue
        logger.info("Firecrawl body-scan resolved %s → %s", source_url, candidate)
        return candidate
    return None


async def find_direct_apply(
    company: str,
    title: str,
    source_url: str | None,
) -> str | None:
    """Top-level orchestrator: cheapest paths first.

    1. If source URL is already on a known ATS → use it (zero network).
    2. Follow source URL's redirect chain — aggregators often 30x to the
       ATS for free (~200ms).
    3. For known-difficult aggregators (WeWorkRemotely, DailyRemote,
       etc.) where the apply link is gated behind JS / paywall UX,
       fall through to Firecrawl which renders the page properly.
    4. Slug-guess across Greenhouse → Lever → Ashby → SmartRecruiters
       (1-12s, cached on the row).
    5. Otherwise → None, caller falls back to source URL.
    """
    if source_url and is_ats_url(source_url):
        return source_url

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        follow_redirects=True,
    ) as client:
        # Step 2: cheap httpx GET + body scan
        if source_url:
            via_redirect = await follow_to_ats(client, source_url)
            if via_redirect:
                return via_redirect

    # Step 3: Firecrawl fallback for known-difficult aggregators
    if source_url and _needs_firecrawl(source_url):
        try:
            via_firecrawl = await follow_to_ats_via_firecrawl(source_url)
            if via_firecrawl:
                return via_firecrawl
        except Exception as e:  # noqa: BLE001
            logger.warning("Firecrawl fallback failed for %s: %s", source_url, e)

    # Step 4: API resolve (opens its own client with JSON headers)
    return await resolve_ats_url(company, title)
