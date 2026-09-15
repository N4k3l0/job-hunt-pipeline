"""Read the jobs out of a LinkedIn job alert email.

Written against the "email_job_alert_digest_01" template (September 2026):
a header "Your job alert for <search>", a subhead "New jobs in <location>
match your preferences.", then one card per job. Every link in a card
points to linkedin.com/comm/jobs/view/<job id>, and its `trk` parameter
names the email section and the card's place in it, e.g.
`primary_job_list-0-jobcard_body_1_jobid_4465475827`. A card's visible
text is the title, "Company · Location (Remote)", then optional lines such
as a salary ("$74K-$76K / year") or "Easy Apply".

The job id in the link path is what identifies a job, so a changed layout
still yields the ids; only the other details degrade.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from app.services.enrichment.job_enricher import annual_salary

_JOB_LINK_RE = re.compile(
    r"""href\s*=\s*["']https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:comm/)?jobs/view/(\d{5,20})[^"']*["']""",
    re.I,
)
_TRK_RE = re.compile(r"trk=[^\"'&]*?-([a-z_]+)-\d+-(?:company_logo|job_posting|jobcard_body)_(\d+)_jobid_(\d+)", re.I)
_ANY_LINK_RE = re.compile(r"<a\b", re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_HIDDEN_RE = re.compile(r"<(style|head|title|script)\b[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")

_WORKPLACE_RE = re.compile(r"\s*\((Remote|Hybrid|On-site|Onsite)\)\s*$", re.I)
_REMOTE_TYPES = {"remote": "full_remote", "hybrid": "hybrid", "on-site": "onsite", "onsite": "onsite"}

_CURRENCIES = {"US$": "USD", "CA$": "CAD", "A$": "AUD", "$": "USD", "€": "EUR", "£": "GBP", "₦": "NGN", "₹": "INR"}
_CURRENCY = r"(?:US\$|CA\$|A\$|\$|€|£|₦|₹)"
_SALARY_RE = re.compile(
    rf"(?P<cur>{_CURRENCY})\s?(?P<min>\d[\d.,]*)\s?(?P<kmin>[KkMm])?"
    rf"(?:\s*[-–]\s*{_CURRENCY}?\s?(?P<max>\d[\d.,]*)\s?(?P<kmax>[KkMm])?)?"
    r"\s*/\s*(?P<period>yr|year|mo|month|wk|week|day|hr|hour)\b"
)
_PERIODS = {"yr": "year", "year": "year", "mo": "month", "month": "month", "wk": "week", "week": "week",
            "day": "day", "hr": "hour", "hour": "hour"}

# Labels are short lines; anything longer is description-like noise.
_MAX_LABEL_CHARS = 60
_MAX_LABELS = 5
# Where the last card ends when nothing follows it.
_LAST_CARD_CHARS = 8000


@dataclass
class AlertJob:
    linkedin_job_id: str
    position: int
    title: str
    list_name: str | None = None
    company: str | None = None
    location: str | None = None
    remote_type: str | None = None
    salary_text: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    labels: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.linkedin.com/jobs/view/{self.linkedin_job_id}"


@dataclass
class ParsedAlert:
    search: str | None
    location: str | None
    jobs: list[AlertJob]


def _pieces(fragment: str) -> list[str]:
    """Visible text, one entry per element."""
    fragment = _HIDDEN_RE.sub(" ", _COMMENT_RE.sub(" ", fragment))
    out = []
    for raw in _TAG_RE.split(fragment):
        text = re.sub(r"\s+", " ", html.unescape(raw)).strip()
        if text:
            out.append(text)
    return out


def _amount(value: str | None, suffix: str | None) -> float | None:
    if not value:
        return None
    try:
        number = float(value.replace(",", ""))
    except ValueError:
        return None
    return number * {"k": 1_000, "m": 1_000_000}.get((suffix or "").lower(), 1)


def parse_salary(text: str) -> tuple[int | None, int | None, str | None] | None:
    """(annual min, annual max, currency) from e.g. "$74K-$76K / year"."""
    m = _SALARY_RE.search(text)
    if not m:
        return None
    period = _PERIODS[m.group("period").lower()]
    low = _amount(m.group("min"), m.group("kmin") or m.group("kmax"))
    high = _amount(m.group("max"), m.group("kmax"))
    return (
        annual_salary(low, period) if low is not None else None,
        annual_salary(high, period) if high is not None else None,
        _CURRENCIES.get(m.group("cur")),
    )


def _card(job_id: str, position: int, list_name: str | None, pieces: list[str]) -> AlertJob | None:
    if not pieces:
        return None
    job = AlertJob(linkedin_job_id=job_id, position=position, list_name=list_name, title=pieces[0][:500])
    for piece in pieces[1:]:
        if job.company is None and "·" in piece:
            company, _, location = piece.partition("·")
            job.company = company.strip()[:500] or None
            location = location.strip()
            workplace = _WORKPLACE_RE.search(location)
            if workplace:
                job.remote_type = _REMOTE_TYPES[workplace.group(1).lower()]
                location = location[: workplace.start()].strip()
            job.location = location[:500] or None
        elif job.salary_text is None and _SALARY_RE.search(piece):
            job.salary_text = piece[:500]
            job.salary_min, job.salary_max, job.salary_currency = parse_salary(piece)
        elif len(piece) <= _MAX_LABEL_CHARS and len(job.labels) < _MAX_LABELS:
            job.labels.append(piece)
    return job


def parse_linkedin_alert(body: str) -> ParsedAlert:
    """Every job in the email, in the order LinkedIn listed them."""
    body = body or ""
    first_link: dict[str, int] = {}
    last_link: dict[str, int] = {}
    placement: dict[str, tuple[str | None, int | None]] = {}
    for m in _JOB_LINK_RE.finditer(body):
        job_id = m.group(1)
        start = body.rfind("<", 0, m.start())
        first_link.setdefault(job_id, start)
        last_link[job_id] = m.end()
        trk = _TRK_RE.search(m.group(0))
        if trk and trk.group(3) == job_id and job_id not in placement:
            placement[job_id] = (trk.group(1).lower(), int(trk.group(2)))

    ordered = sorted(first_link, key=first_link.get)
    jobs: list[AlertJob] = []
    for n, job_id in enumerate(ordered):
        if n + 1 < len(ordered):
            end = first_link[ordered[n + 1]]
        else:
            following = _ANY_LINK_RE.search(body, last_link[job_id])
            end = following.start() if following else last_link[job_id] + _LAST_CARD_CHARS
        list_name, position = placement.get(job_id, (None, None))
        job = _card(job_id, position if position is not None else n, list_name, _pieces(body[first_link[job_id]:end]))
        if job:
            jobs.append(job)

    header_end = first_link[ordered[0]] if ordered else len(body)
    search = location = None
    header = _pieces(body[:header_end])
    for i, piece in enumerate(header):
        if piece.lower().startswith("your job alert for"):
            rest = piece[len("your job alert for"):].strip()
            search = rest or (header[i + 1] if i + 1 < len(header) else None)
        m = re.match(r"New jobs in (.+?) match your preferences", piece, re.I)
        if m:
            location = m.group(1)
    return ParsedAlert(search=(search or None) and search[:255], location=(location or None) and location[:255], jobs=jobs)
