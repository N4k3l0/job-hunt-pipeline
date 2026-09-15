"""Where remote postings accept applicants from, and keyword pre-filters.

Several sources tag postings with a region or location restriction
(Remotive: `candidate_required_location`, Himalayas: `locationRestrictions`,
WeWorkRemotely: `region` text in the title or description).
`eligible_countries_from_text` turns those into ISO country codes, and only
when the source is explicit, so an unclear posting is never hidden.
"""

from __future__ import annotations

import re

_GLOBAL_HINTS: tuple[str, ...] = (
    "worldwide", "anywhere", "global", "any country", "any location", "all countries",
)

EU_COUNTRIES: tuple[str, ...] = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
)
EUROPE_COUNTRIES: tuple[str, ...] = EU_COUNTRIES + ("GB", "CH", "NO", "IS", "UA", "RS", "TR")

# Region names that map cleanly to a country set. Broad regions that
# include much of the world (EMEA, Africa, APAC) are deliberately left out:
# treating them as restrictions would hide jobs people can actually take.
_REGION_COUNTRIES: dict[str, tuple[str, ...]] = {
    "european union": EU_COUNTRIES,
    "eu": EU_COUNTRIES,
    "europe": EUROPE_COUNTRIES,
    "north america": ("US", "CA", "MX"),
    "latam": ("MX", "BR", "AR", "CO", "CL", "PE", "UY", "EC", "CR", "PA"),
    "latin america": ("MX", "BR", "AR", "CO", "CL", "PE", "UY", "EC", "CR", "PA"),
}

_ONLY_PATTERNS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"\b(?:us|usa|united states)(?:[-\s]based)?[-\s]only\b", re.I), ("US",)),
    (re.compile(r"must (?:be|reside)(?: located)? in (?:the )?(?:us|usa|united states)", re.I), ("US",)),
    (re.compile(r"work authoriz(?:ation|ed) in the (?:us|united states) required", re.I), ("US",)),
    (re.compile(r"\b(?:uk|united kingdom)[-\s]only\b", re.I), ("GB",)),
    (re.compile(r"\beu[-\s]only\b", re.I), EU_COUNTRIES),
    (re.compile(r"must be (?:located|based) in (?:the eu|the european union)\b", re.I), EU_COUNTRIES),
    (re.compile(r"must be (?:located|based) in europe\b", re.I), EUROPE_COUNTRIES),
    (re.compile(r"\bcanad(?:a|ian)[-\s]only\b", re.I), ("CA",)),
)


def eligible_countries_from_text(
    *,
    location_restrictions: list[str] | None = None,
    candidate_required_location: str | None = None,
    region_text: str | None = None,
    description: str | None = None,
) -> list[str] | None:
    """ISO-2 codes a remote posting is restricted to, or None if it looks
    open to anyone (or we can't tell). Only returns a list when the source
    is explicit, so an unclear posting is never hidden from anyone."""
    from app.services.parsing.normalizer import COUNTRY_MAP

    structured_parts = [
        *(location_restrictions or []),
        candidate_required_location or "",
        region_text or "",
    ]
    structured = " ".join(p for p in structured_parts if p).strip()

    if structured and any(hint in structured.lower() for hint in _GLOBAL_HINTS):
        return None

    found: set[str] = set()
    for text in (structured, description or ""):
        for pattern, codes in _ONLY_PATTERNS:
            if pattern.search(text):
                found.update(codes)
    if structured:
        lowered = f" {structured.lower()} "
        for name, codes in _REGION_COUNTRIES.items():
            if re.search(rf"\b{re.escape(name)}\b", lowered):
                found.update(codes)
        for name, code in COUNTRY_MAP.items():
            if len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", lowered):
                found.add(code)
    return sorted(found) or None


def matches_keywords(text: str, keywords: set[str] | None) -> bool:
    """Cheap substring match used to filter pre-ingest. Returns True if no
    keywords were provided (caller asked for the full feed)."""
    if not keywords:
        return True
    lower = text.lower()
    return any(kw in lower for kw in keywords)
