"""Geography, visa, and remote scoring.

Scoring weights:
- Geography fit: 0-15
- Remote fit: 0-5
- Visa fit: 0-10 (split from geo for clarity in scoring, but counts toward the 15 geo allocation)

Note: visa_score is reported separately but the total geo+remote+visa = 30 max.
"""


def score_geography(
    job_country: str | None,
    job_remote_type: str | None,
    job_sponsorship: bool | None,
    job_visa_notes: str | None,
    preferred_countries: list[str],
    visa_statuses: dict,
    remote_preference: str,
) -> dict:
    """Score geography, visa, and remote fit.

    Args:
        job_country: ISO country code of the job
        job_remote_type: full_remote, hybrid, onsite, or None
        job_sponsorship: True/False/None
        job_visa_notes: Raw visa notes text
        preferred_countries: User's preferred country codes
        visa_statuses: Dict of country_code -> status (citizen, permanent_resident, work_visa, need_sponsorship)
        remote_preference: any, full_remote, hybrid, onsite

    Returns:
        Dict with geo_score, remote_score, visa_score, reasoning
    """
    reasoning = {}

    # ── Geography (0-15) ──────────────────────────────────────────────────
    geo_score = 0.0

    if not job_country:
        if job_remote_type == "full_remote":
            geo_score = 12.0  # Remote with no country restriction is good
            reasoning["geo"] = "remote, no country restriction"
        else:
            geo_score = 7.0  # Unknown location, neutral
            reasoning["geo"] = "location unknown"
    elif preferred_countries and job_country.upper() in [c.upper() for c in preferred_countries]:
        geo_score = 15.0
        reasoning["geo"] = f"{job_country} is a preferred country"
    elif preferred_countries:
        geo_score = 3.0  # Country not in preferences
        reasoning["geo"] = f"{job_country} not in preferred countries"
    else:
        geo_score = 10.0  # No preferences set, neutral-positive
        reasoning["geo"] = "no country preferences set"

    # ── Remote Fit (0-5) ──────────────────────────────────────────────────
    remote_score = 0.0

    if remote_preference == "any" or not remote_preference:
        remote_score = 5.0  # No preference, everything fits
    elif remote_preference == "full_remote":
        if job_remote_type == "full_remote":
            remote_score = 5.0
        elif job_remote_type == "hybrid":
            remote_score = 2.0
        else:
            remote_score = 0.0
    elif remote_preference == "hybrid":
        if job_remote_type in ("hybrid", "full_remote"):
            remote_score = 5.0
        else:
            remote_score = 2.0
    elif remote_preference == "onsite":
        if job_remote_type == "onsite":
            remote_score = 5.0
        else:
            remote_score = 3.0

    reasoning["remote"] = f"job={job_remote_type or 'unknown'}, preference={remote_preference}"

    # ── Visa Fit (0-10) ───────────────────────────────────────────────────
    visa_score = 5.0  # Default neutral

    if job_country and visa_statuses:
        status = visa_statuses.get(job_country.upper())
        if status in ("citizen", "permanent_resident"):
            visa_score = 10.0
            reasoning["visa"] = f"authorized to work in {job_country}"
        elif status == "work_visa":
            visa_score = 8.0
            reasoning["visa"] = f"have work visa for {job_country}"
        elif status == "need_sponsorship":
            if job_sponsorship is True:
                visa_score = 7.0
                reasoning["visa"] = f"need sponsorship, job offers it"
            elif job_sponsorship is False:
                visa_score = 1.0
                reasoning["visa"] = f"need sponsorship, job does NOT offer it"
            else:
                visa_score = 4.0
                reasoning["visa"] = f"need sponsorship, unknown if offered"
        else:
            # No visa info for this country
            if job_remote_type == "full_remote":
                visa_score = 6.0
                reasoning["visa"] = "remote job, visa may not apply"
            else:
                visa_score = 3.0
                reasoning["visa"] = f"no work authorization info for {job_country}"
    elif not job_country:
        visa_score = 5.0
        reasoning["visa"] = "no country specified"
    else:
        visa_score = 5.0
        reasoning.setdefault("visa", "no visa preferences set")

    return {
        "geo_score": geo_score,
        "remote_score": remote_score,
        "visa_score": visa_score,
        "reasoning": reasoning,
    }
