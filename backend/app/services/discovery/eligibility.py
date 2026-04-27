"""Nigeria-friendly eligibility heuristics for incoming job postings.

Several of our newer sources tag postings with a region/location-restriction
string (Remotive: `candidate_required_location`, Himalayas: `locationRestrictions`,
WeWorkRemotely: `region` text in the title or description). We classify each
posting as `True` (eligible), `False` (ruled out by an explicit US/EU-only
restriction), or `None` (unknown — let it through and let scoring sort it).

Keep the rules narrow on purpose. False positives (admitting jobs that are
actually US-only) are recoverable through scoring; false negatives (filtering
out jobs that *would* take a Nigerian) are not, since the user never sees them.
"""

from __future__ import annotations

import re

# Phrases that strongly imply a posting is open globally — including to Nigeria.
_NIGERIA_FRIENDLY_HINTS: tuple[str, ...] = (
    "worldwide",
    "anywhere",
    "global",
    "any country",
    "any location",
    "all countries",
    "remote, anywhere",
    "fully remote",
    "africa",
    "nigeria",
    "emea",  # broad — includes Africa per most employers' definition
)

# Phrases that explicitly rule out Nigeria. We're conservative — only patterns
# that are clearly hard exclusions, not "preferred location is X".
_HARD_EXCLUSION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"must (?:be|reside)(?: located)? in (?:the )?(?:us|usa|united states)", re.I),
    re.compile(r"us(?:a|-based| only| residents only| citizens only)\b", re.I),
    re.compile(r"\bus citizens\b.{0,40}\bonly\b", re.I),
    re.compile(r"\bonly\b.{0,40}\b(?:us|usa) (?:residents|citizens)\b", re.I),
    re.compile(r"work authoriz(?:ation|ed) in the (?:us|united states) required", re.I),
    re.compile(r"\b(?:eu|uk)[-\s]only\b", re.I),
    re.compile(r"must be located in (?:europe|the eu)", re.I),
    re.compile(r"\bcanad(?:a|ian)[-\s]only\b", re.I),
)


def _has_friendly_hint(text: str) -> bool:
    lower = text.lower()
    return any(hint in lower for hint in _NIGERIA_FRIENDLY_HINTS)


def _has_hard_exclusion(text: str) -> bool:
    return any(pat.search(text) for pat in _HARD_EXCLUSION_PATTERNS)


def is_nigeria_friendly(
    *,
    location_restrictions: list[str] | None = None,
    candidate_required_location: str | None = None,
    region_text: str | None = None,
    description: str | None = None,
) -> bool | None:
    """Return True / False / None.

    True  — at least one source field explicitly invites global/Africa/Nigeria.
    False — at least one field explicitly rules out non-US (or other hard region).
    None  — we couldn't tell. The job still ingests; scoring decides priority.
    """
    # Combine all the structured fields we have for a "friendly" check.
    structured = " ".join(
        [
            *(location_restrictions or []),
            candidate_required_location or "",
            region_text or "",
        ]
    ).strip()

    if structured and _has_friendly_hint(structured):
        return True

    # Hard exclusions — check structured fields first (high confidence) then
    # the description (lower confidence but still actionable).
    if structured and _has_hard_exclusion(structured):
        return False
    if description and _has_hard_exclusion(description):
        return False

    return None


def matches_keywords(text: str, keywords: set[str] | None) -> bool:
    """Cheap substring match used to filter pre-ingest. Returns True if no
    keywords were provided (caller asked for the full feed)."""
    if not keywords:
        return True
    lower = text.lower()
    return any(kw in lower for kw in keywords)
