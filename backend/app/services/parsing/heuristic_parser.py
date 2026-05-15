"""LLM-free fallback parser for job posting markdown.

Used when Claude/Anthropic is unavailable (e.g. the admin's API balance
hit zero) so URL imports keep working. The output shape matches what
`parse_job_text` returns from the LLM path, just with fewer fields
populated.

The trade-off vs. the LLM parser:
- Title, company, location, raw description: extracted reliably from
  page structure and URL slug.
- required_skills / requirements / keywords: returned as empty arrays.
  The semantic scorer can still operate on raw_description (the JD body
  becomes part of the job's embedding), so the inbox score isn't zero —
  it's just less specific than the LLM-extracted-entities path.

A job parsed this way costs ~$0.001 (Firecrawl only) instead of ~$0.012
(Firecrawl + Sonnet). When the user tops up Anthropic, future imports
automatically go back to the higher-quality LLM path.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# ── URL host → company name extraction ─────────────────────────────────
# Most ATSes encode the employer slug in the URL path. We use that as a
# trustworthy seed for the company name when the page-scraped text is
# noisy or templated.
_ATS_SLUG_PATTERNS = [
    # Greenhouse: boards.greenhouse.io/<slug>/jobs/<id>
    #         or  job-boards.greenhouse.io/<slug>/jobs/<id>
    re.compile(r"^(?:job-)?boards(?:\.eu)?\.greenhouse\.io/([^/]+)", re.I),
    # Lever: jobs.lever.co/<slug>/...
    re.compile(r"^jobs\.lever\.co/([^/]+)", re.I),
    # Ashby: jobs.ashbyhq.com/<slug>/...
    re.compile(r"^jobs\.ashbyhq\.com/([^/]+)", re.I),
    # Workable: apply.workable.com/<slug>/j/... or jobs.workable.com/<slug>
    re.compile(r"^(?:apply|jobs)\.workable\.com/([^/]+)", re.I),
    # SmartRecruiters
    re.compile(r"^jobs\.smartrecruiters\.com/([^/]+)", re.I),
    # Workday: <tenant>.myworkdayjobs.com/<external_route>
    re.compile(r"^([^.]+)\.myworkdayjobs\.com", re.I),
    # Recruitee: <slug>.recruitee.com
    re.compile(r"^([^.]+)\.recruitee\.com", re.I),
    # Teamtailor: <slug>.teamtailor.com
    re.compile(r"^([^.]+)\.teamtailor\.com", re.I),
]

# Markdown patterns we trust as the job title (in priority order).
_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_OG_TITLE_RE = re.compile(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)', re.I)

# Common labeled fields ATSes include (Greenhouse / Lever / Workable use
# either "Location:" lines or dedicated UI chips that come through as
# "Location\n<value>" in markdown).
_LOCATION_LABEL_RE = re.compile(
    r"(?:^|\n)\s*(?:Location|Office|Where)\s*[:\-]\s*([^\n]+)",
    re.I,
)
_REMOTE_HINT_RE = re.compile(r"\b(remote|work from anywhere|fully\s+remote|wfh)\b", re.I)
_HYBRID_HINT_RE = re.compile(r"\b(hybrid|days in office|office days)\b", re.I)
_ONSITE_HINT_RE = re.compile(r"\b(on[\s-]?site|in[\s-]?office|must be located)\b", re.I)


def _company_from_url(url: str) -> str | None:
    """Pull the employer slug from a known ATS host and title-case it.

    boards.greenhouse.io/intercom/...   → "Intercom"
    jobs.lever.co/mistral/...           → "Mistral"
    jobs.ashbyhq.com/fastino-ai/...     → "Fastino Ai"
    """
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return None
    host_and_path = f"{parsed.netloc}{parsed.path}"
    for pat in _ATS_SLUG_PATTERNS:
        m = pat.match(host_and_path)
        if m:
            slug = m.group(1).strip("-_")
            # Hyphens / underscores → spaces, title-case each word.
            words = [w for w in re.split(r"[-_]+", slug) if w]
            return " ".join(w.capitalize() for w in words) or None
    return None


def _title_from_markdown(md: str) -> str | None:
    """Take the first H1 (most ATSes render the job title as H1).
    Fall back to the first H2 if no H1 exists, then to an og:title tag.
    """
    h1 = _H1_RE.search(md)
    if h1:
        candidate = h1.group(1).strip()
        # Filter out obvious non-titles (company landing pages sometimes
        # H1 the company name itself; we'd rather end up with None and
        # let the normalizer flag the row than store the wrong value).
        if 5 <= len(candidate) <= 200:
            return candidate
    h2 = _H2_RE.search(md)
    if h2:
        candidate = h2.group(1).strip()
        if 5 <= len(candidate) <= 200:
            return candidate
    og = _OG_TITLE_RE.search(md)
    if og:
        return og.group(1).strip()
    return None


def _location_from_markdown(md: str) -> str | None:
    """Extract a freeform location string. Prefers a labeled 'Location:'
    line; otherwise scans the first ~3 lines (most ATSes surface it near
    the top)."""
    m = _LOCATION_LABEL_RE.search(md)
    if m:
        return m.group(1).strip(" *_•")[:120] or None
    # Look at the head of the doc for any obvious place name.
    head = "\n".join(md.splitlines()[:15])
    if _REMOTE_HINT_RE.search(head):
        return "Remote"
    return None


def _remote_type_from_text(text: str) -> str | None:
    """Single pass classification — hybrid wins over remote, since both
    keywords often coexist in the same JD."""
    if _HYBRID_HINT_RE.search(text):
        return "hybrid"
    if _ONSITE_HINT_RE.search(text):
        return "onsite"
    if _REMOTE_HINT_RE.search(text):
        return "full_remote"
    return None


def parse_job_heuristic(*, url: str | None, markdown: str) -> dict:
    """LLM-free job extraction. Returns the same shape parse_job_text
    does, with empty arrays for entity fields the LLM would populate."""
    md = markdown or ""

    title = _title_from_markdown(md) or "Untitled role"
    company = _company_from_url(url or "") or "Unknown"
    location = _location_from_markdown(md)
    remote_type = _remote_type_from_text(md)

    logger.info(
        "Heuristic parse: title=%r company=%r location=%r remote=%r (url=%s)",
        title, company, location, remote_type, url,
    )

    # CRITICAL: description_summary is what gets stored as Job.raw_description,
    # which is what the Voyage embedder ingests for semantic scoring. Leaving
    # it None means the job never gets an embedding and never gets a score
    # above ~5pts (since the heuristic parser also can't fill skills /
    # requirements / keywords). Use the cleaned markdown body as the
    # description instead — it contains the real JD content, the embedder
    # handles long inputs gracefully, and the semantic scorer can produce
    # a useful match score from that alone.
    description = _trim_markdown_for_embedding(md)

    return {
        "title": title,
        "company": company,
        "location": location,
        "country": None,  # Let the country normalizer infer downstream
        "remote_type": remote_type,
        "salary_text": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "employment_type": None,
        "seniority": None,
        "application_type": "url",
        "description_summary": description,
        "required_skills": [],
        "nice_to_have_skills": [],
        "requirements": [],
        "keywords": [],
        "years_experience_min": None,
        "years_experience_max": None,
        "visa_notes": None,
        "sponsorship_available": None,
        "application_questions": [],
        "apply_url": url,
        "contact_email": None,
        "deadline": None,
    }


def _trim_markdown_for_embedding(md: str) -> str:
    """Strip Firecrawl-rendered boilerplate (nav links, footer junk, image
    refs) so the embedded text is mostly real JD content. Caps at 4000
    chars — Voyage handles longer but the marginal info past that is
    usually template/footer noise."""
    if not md:
        return ""
    cleaned = re.sub(r"!\[.*?\]\(.*?\)", "", md)         # image refs
    cleaned = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", cleaned)  # link → text
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)         # collapse blank lines
    return cleaned.strip()[:4000]
