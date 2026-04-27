import hashlib
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobEntity, JobSource

logger = logging.getLogger(__name__)

# Company name suffixes to strip for normalization
COMPANY_SUFFIXES = re.compile(
    r"\s*\b(inc\.?|llc\.?|ltd\.?|gmbh|ag|se|corp\.?|corporation|co\.?|company|plc|limited)\s*$",
    re.IGNORECASE,
)

# Title level indicators to strip for dedup
TITLE_LEVELS = re.compile(r"\s*\b(ii|iii|iv|l\d+|level\s+\d+)\s*$", re.IGNORECASE)

# Title abbreviation map
TITLE_ABBREVS = {
    "sr.": "senior",
    "sr": "senior",
    "jr.": "junior",
    "jr": "junior",
    "vp": "vice president",
    "mgr": "manager",
    "eng": "engineer",
    "dev": "developer",
}

# Country name to ISO code mapping
COUNTRY_MAP = {
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "canada": "CA",
    "germany": "DE",
    "deutschland": "DE",
    "france": "FR",
    "netherlands": "NL",
    "holland": "NL",
    "austria": "AT",
    "switzerland": "CH",
    "ireland": "IE",
    "sweden": "SE",
    "denmark": "DK",
    "norway": "NO",
    "finland": "FI",
    "spain": "ES",
    "italy": "IT",
    "portugal": "PT",
    "belgium": "BE",
    "poland": "PL",
    "australia": "AU",
    "singapore": "SG",
    "india": "IN",
    "israel": "IL",
}


def normalize_company(name: str) -> str:
    """Normalize a company name for dedup comparison."""
    name = name.strip().lower()
    name = re.sub(r"^the\s+", "", name)
    name = COMPANY_SUFFIXES.sub("", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def normalize_title(title: str) -> str:
    """Normalize a job title for dedup comparison."""
    title = title.strip().lower()
    # Expand abbreviations
    for abbrev, full in TITLE_ABBREVS.items():
        title = re.sub(rf"\b{re.escape(abbrev)}\b", full, title)
    # Strip level indicators for dedup
    title = TITLE_LEVELS.sub("", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def normalize_country(country_str: str | None) -> str | None:
    """Normalize a country string to ISO code."""
    if not country_str:
        return None
    country_str = country_str.strip()
    # Already an ISO code
    if len(country_str) == 2 and country_str.isalpha():
        return country_str.upper()
    # Look up in map
    return COUNTRY_MAP.get(country_str.lower(), country_str.upper()[:2])


def classify_remote(text: str | None, is_description: bool = False) -> str | None:
    """Classify remote type from text.

    For titles/locations, simple keyword matching works.
    For descriptions, use stricter patterns to avoid false positives
    like 'remote talent' or 'remote teams' in product descriptions.
    """
    if not text:
        return None
    text = text.lower()

    # Check hybrid first (often says "remote" + "hybrid" together)
    hybrid_signals = [
        "hybrid", "days in office", "days on-site", "partial remote",
        "in-office days", "office days per week",
    ]
    if any(s in text for s in hybrid_signals):
        return "hybrid"

    # Strict remote signals — safe for both titles and descriptions
    strict_remote = [
        "fully remote", "100% remote", "remote position", "remote role",
        "work from home", "work remotely", "remote-first", "remote first",
        "location: remote", "work from anywhere", "remote job",
        "telecommute", "this is a remote", "position is remote",
        "role is remote", "(remote)", "- remote",
    ]
    if any(s in text for s in strict_remote):
        return "full_remote"

    # For titles and locations only — simple "remote" is reliable
    if not is_description:
        if "remote" in text and "remote control" not in text:
            return "full_remote"

    # Check onsite
    onsite_signals = [
        "on-site only", "onsite only", "in-office only", "no remote",
        "office based", "office-based", "must be located",
    ]
    if any(s in text for s in onsite_signals):
        return "onsite"

    return None


def compute_canonical_hash(company: str, title: str, city: str | None, country: str | None) -> str:
    """Compute a canonical hash for deduplication.

    Uses normalized company + title + city + country.
    """
    parts = [
        normalize_company(company),
        normalize_title(title),
        (city or "").strip().lower(),
        (country or "").strip().lower(),
    ]
    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


# Words that some sources use in the location field but are not real cities.
# We strip these out so they don't pollute the canonical hash (otherwise
# "Worldwide" jobs from Himalayas and "Anywhere" jobs from Remotive get
# different hashes for the same role).
_NON_PLACE_TERMS = {
    "worldwide", "anywhere", "remote", "global", "any country", "any location",
    "all countries", "everywhere", "all", "n/a", "none", "various",
    "fully remote", "100% remote", "remote-first", "emea", "americas",
    "africa", "asia", "europe",
}


def extract_city(location: str | None) -> str | None:
    """Extract city from a location string like 'San Francisco, CA' or 'London, UK'.

    Returns None for placeholder strings like 'Worldwide' / 'Anywhere' so the
    canonical hash stays stable across sources that use different wording for
    'no specific city'.
    """
    if not location:
        return None
    first = location.split(",")[0].strip()
    if not first:
        return None
    if first.lower() in _NON_PLACE_TERMS:
        return None
    return first


# Known tracking / session params that shouldn't differentiate the same job URL.
_TRACKING_PARAMS: frozenset[str] = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "src", "source", "referrer", "trk", "trkid",
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid",
    "_hsenc", "_hsmi", "hsCtaTracking",
})


def normalize_url(url: str | None) -> str | None:
    """Normalize a job URL for dedup comparison.

    - Lowercase scheme + host
    - Strip fragment
    - Drop common tracking query params (but preserve real query params like
      LinkedIn's `currentJobId` that actually identify the posting)
    - Strip trailing slash
    Returns None for empty input.
    """
    if not url:
        return None
    from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip().rstrip("/").lower() or None

    if not parsed.scheme or not parsed.netloc:
        return url.strip().rstrip("/").lower() or None

    kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in _TRACKING_PARAMS]
    # Strip trailing slash from the path itself (so trailing-slash differences
    # don't survive into URLs like `.../view/?id=1` vs `.../view?id=1`).
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        query=urlencode(kept),
        fragment="",
    )
    return urlunparse(cleaned)


async def get_or_create_source(db: AsyncSession, source_name: str, source_type: str = "manual") -> JobSource:
    """Get or create a job source record."""
    result = await db.execute(
        select(JobSource).where(JobSource.name == source_name)
    )
    source = result.scalar_one_or_none()
    if not source:
        source = JobSource(name=source_name, source_type=source_type)
        db.add(source)
        await db.flush()
    return source


async def normalize_and_store_job(
    db: AsyncSession,
    parsed_data: dict,
    raw_content: str,
    source_name: str,
    source_type: str = "manual",
    external_id: str | None = None,
    job_url: str | None = None,
) -> Job | None:
    """Normalize parsed job data and store in database.

    Returns the Job if stored, None if it was a duplicate.
    """
    company = parsed_data.get("company", "Unknown")
    title = parsed_data.get("title", "Unknown")
    location = parsed_data.get("location")
    country = normalize_country(parsed_data.get("country"))
    city = extract_city(location)

    # Compute canonical hash
    canonical_hash = compute_canonical_hash(company, title, city, country)

    # Check for duplicates
    from app.services.deduplication.dedup_service import check_duplicate
    is_dup, dup_job_id = await check_duplicate(db, canonical_hash, parsed_data.get("description_summary", ""))
    if is_dup:
        logger.info("Duplicate job found: %s at %s (duplicate of %s)", title, company, dup_job_id)
        return None

    # Get or create source
    source = await get_or_create_source(db, source_name, source_type)

    # Classify remote type
    remote_type = parsed_data.get("remote_type") or classify_remote(location)

    # Parse deadline
    deadline = None
    if parsed_data.get("deadline"):
        try:
            deadline = datetime.fromisoformat(parsed_data["deadline"])
        except (ValueError, TypeError):
            pass

    # Create job record
    job = Job(
        external_id=external_id,
        source_id=source.id,
        company=company,
        title=title,
        location=location,
        country=country,
        remote_type=remote_type,
        job_url=job_url or parsed_data.get("apply_url"),
        apply_url=parsed_data.get("apply_url"),
        salary_text=parsed_data.get("salary_text"),
        salary_min=parsed_data.get("salary_min"),
        salary_max=parsed_data.get("salary_max"),
        salary_currency=parsed_data.get("salary_currency"),
        raw_description=parsed_data.get("description_summary"),
        raw_content=raw_content,
        employment_type=parsed_data.get("employment_type"),
        seniority=parsed_data.get("seniority"),
        application_type=parsed_data.get("application_type"),
        canonical_hash=canonical_hash,
        status="enriched",
        parsed_at=datetime.now(timezone.utc),
        expires_at=deadline,
    )
    db.add(job)
    await db.flush()

    # Create job entities
    entities = JobEntity(
        job_id=job.id,
        skills=parsed_data.get("required_skills", []),
        requirements=parsed_data.get("requirements", []),
        keywords=parsed_data.get("keywords", []),
        nice_to_have=parsed_data.get("nice_to_have_skills", []),
        visa_notes=parsed_data.get("visa_notes"),
        sponsorship_available=parsed_data.get("sponsorship_available"),
        application_questions=parsed_data.get("application_questions", []),
        years_experience_min=parsed_data.get("years_experience_min"),
        years_experience_max=parsed_data.get("years_experience_max"),
    )
    db.add(entities)

    logger.info("Stored job: %s at %s [%s] (id=%s)", title, company, source_name, job.id)
    return job
