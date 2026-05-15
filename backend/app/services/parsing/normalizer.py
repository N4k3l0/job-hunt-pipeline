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

# Country name to ISO code mapping. Used both at ingest (to populate
# Job.country from aggregator strings) and at filter time (to detect
# restricted-remote postings whose country field is NULL but whose
# location text mentions specific countries — e.g. "Remote (Brazil,
# Colombia, Philippines)" which should NOT show up for a candidate
# targeting NL/DE/UK).
COUNTRY_MAP = {
    # Europe (most user preferences live here)
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "germany": "DE", "deutschland": "DE",
    "france": "FR",
    "netherlands": "NL", "holland": "NL",
    "austria": "AT",
    "switzerland": "CH",
    "ireland": "IE", "republic of ireland": "IE",
    "sweden": "SE", "denmark": "DK", "norway": "NO", "finland": "FI",
    "iceland": "IS",
    "spain": "ES", "italy": "IT", "portugal": "PT",
    "belgium": "BE", "luxembourg": "LU",
    "poland": "PL", "czech republic": "CZ", "czechia": "CZ",
    "slovakia": "SK", "hungary": "HU", "romania": "RO", "bulgaria": "BG",
    "greece": "GR", "croatia": "HR", "slovenia": "SI", "estonia": "EE",
    "latvia": "LV", "lithuania": "LT", "serbia": "RS", "ukraine": "UA",
    "turkey": "TR", "russia": "RU",
    # North America
    "united states": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "canada": "CA",
    # Latin America (common in "remote restricted" postings)
    "mexico": "MX", "brazil": "BR", "brasil": "BR",
    "argentina": "AR", "colombia": "CO", "chile": "CL", "peru": "PE",
    "uruguay": "UY", "ecuador": "EC", "venezuela": "VE", "bolivia": "BO",
    "costa rica": "CR", "panama": "PA", "guatemala": "GT",
    "dominican republic": "DO", "honduras": "HN", "nicaragua": "NI",
    # Asia / APAC
    "australia": "AU", "new zealand": "NZ",
    "singapore": "SG", "india": "IN", "israel": "IL",
    "philippines": "PH", "indonesia": "ID", "malaysia": "MY",
    "thailand": "TH", "vietnam": "VN", "viet nam": "VN",
    "japan": "JP", "south korea": "KR", "korea": "KR",
    "china": "CN", "hong kong": "HK", "taiwan": "TW",
    "pakistan": "PK", "bangladesh": "BD", "sri lanka": "LK",
    "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA",
    # Africa
    "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "ghana": "GH",
    "egypt": "EG", "morocco": "MA", "tunisia": "TN",
}


# Major cities mapped to ISO country codes. Used by the inbox filter to
# catch restricted-remote postings whose location text spells out a city
# but not a country — "Remote, Bangalore" should be treated as India,
# "Berlin only" as Germany, etc. Kept separate from COUNTRY_MAP so
# normalize_country() doesn't silently start converting city strings;
# it stays focused on country-name → ISO duty.
CITY_TO_COUNTRY = {
    # Netherlands
    "amsterdam": "NL", "rotterdam": "NL", "the hague": "NL", "den haag": "NL",
    "utrecht": "NL", "eindhoven": "NL", "groningen": "NL", "delft": "NL",
    "leiden": "NL", "haarlem": "NL", "schiphol": "NL", "hilversum": "NL",
    "hoofddorp": "NL", "amstelveen": "NL",
    # Germany
    "berlin": "DE", "munich": "DE", "münchen": "DE", "hamburg": "DE",
    "frankfurt": "DE", "cologne": "DE", "köln": "DE", "stuttgart": "DE",
    "düsseldorf": "DE", "dusseldorf": "DE", "leipzig": "DE", "dresden": "DE",
    "heidelberg": "DE", "karlsruhe": "DE", "nuremberg": "DE",
    # United Kingdom
    "london": "GB", "manchester": "GB", "edinburgh": "GB", "glasgow": "GB",
    "birmingham": "GB", "liverpool": "GB", "leeds": "GB", "cambridge": "GB",
    "oxford": "GB", "bristol": "GB", "belfast": "GB", "cardiff": "GB",
    "newcastle": "GB",
    # Ireland
    "dublin": "IE", "cork": "IE", "galway": "IE", "limerick": "IE",
    # France
    "paris": "FR", "lyon": "FR", "marseille": "FR", "toulouse": "FR",
    "bordeaux": "FR", "nantes": "FR",
    # Spain / Portugal / Italy
    "madrid": "ES", "barcelona": "ES", "valencia": "ES", "seville": "ES",
    "lisbon": "PT", "porto": "PT",
    "milan": "IT", "rome": "IT", "turin": "IT", "naples": "IT",
    # Other Europe
    "brussels": "BE", "antwerp": "BE", "ghent": "BE",
    "vienna": "AT", "graz": "AT", "salzburg": "AT",
    "zurich": "CH", "geneva": "CH", "basel": "CH", "bern": "CH",
    "stockholm": "SE", "gothenburg": "SE", "malmö": "SE", "malmo": "SE",
    "copenhagen": "DK", "aarhus": "DK",
    "oslo": "NO", "bergen": "NO",
    "helsinki": "FI",
    "warsaw": "PL", "krakow": "PL", "kraków": "PL", "gdansk": "PL", "wrocław": "PL",
    "prague": "CZ", "praha": "CZ",
    # United States — most-named tech hubs in restricted-remote postings
    "new york": "US", "nyc": "US", "san francisco": "US", "los angeles": "US",
    "seattle": "US", "austin": "US", "boston": "US", "chicago": "US",
    "denver": "US", "atlanta": "US", "miami": "US", "san diego": "US",
    "portland": "US", "dallas": "US", "houston": "US", "phoenix": "US",
    "minneapolis": "US", "philadelphia": "US", "washington dc": "US",
    "san jose": "US", "salt lake city": "US",
    # Canada
    "toronto": "CA", "montreal": "CA", "vancouver": "CA", "ottawa": "CA",
    "calgary": "CA",
    # India — by far the most common "restricted remote" location
    "bangalore": "IN", "bengaluru": "IN", "mumbai": "IN", "delhi": "IN",
    "new delhi": "IN", "chennai": "IN", "hyderabad": "IN", "pune": "IN",
    "kolkata": "IN", "gurgaon": "IN", "gurugram": "IN", "noida": "IN",
    "ahmedabad": "IN",
    # Latin America
    "são paulo": "BR", "sao paulo": "BR", "rio de janeiro": "BR",
    "brasilia": "BR", "brasília": "BR", "recife": "BR", "belo horizonte": "BR",
    "porto alegre": "BR",
    "mexico city": "MX", "ciudad de mexico": "MX", "cdmx": "MX",
    "guadalajara": "MX", "monterrey": "MX",
    "buenos aires": "AR", "cordoba": "AR", "córdoba": "AR", "rosario": "AR",
    "bogotá": "CO", "bogota": "CO", "medellín": "CO", "medellin": "CO",
    "cali": "CO", "barranquilla": "CO",
    "santiago": "CL",
    "lima": "PE",
    # APAC
    "manila": "PH", "cebu": "PH", "makati": "PH", "quezon city": "PH",
    "jakarta": "ID", "bali": "ID", "surabaya": "ID", "bandung": "ID",
    "kuala lumpur": "MY", "penang": "MY",
    "bangkok": "TH", "chiang mai": "TH",
    "ho chi minh": "VN", "hanoi": "VN", "saigon": "VN",
    "tokyo": "JP", "osaka": "JP", "kyoto": "JP",
    "seoul": "KR", "busan": "KR",
    "beijing": "CN", "shanghai": "CN", "shenzhen": "CN", "guangzhou": "CN",
    "hong kong": "HK", "taipei": "TW",
    "karachi": "PK", "lahore": "PK", "islamabad": "PK",
    "dhaka": "BD", "chittagong": "BD",
    "sydney": "AU", "melbourne": "AU", "brisbane": "AU", "perth": "AU",
    "auckland": "NZ", "wellington": "NZ",
    # MENA / Africa
    "dubai": "AE", "abu dhabi": "AE",
    "riyadh": "SA", "jeddah": "SA",
    "tel aviv": "IL",
    "istanbul": "TR", "ankara": "TR",
    "cairo": "EG", "alexandria": "EG",
    "lagos": "NG", "abuja": "NG",
    "nairobi": "KE",
    "johannesburg": "ZA", "cape town": "ZA", "joburg": "ZA",
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

    # Create job entities — embedding gets backfilled in a batched pass
    # AFTER ingest finishes (see _ingest_raw_jobs in discovery_tasks).
    # Inline per-row embed would mean 1k+ separate API calls during a
    # discovery batch, blowing Vercel's 60s function budget.
    entities = JobEntity(
        job_id=job.id,
        skills=parsed_data.get("required_skills", []) or [],
        requirements=parsed_data.get("requirements", []) or [],
        keywords=parsed_data.get("keywords", []) or [],
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
