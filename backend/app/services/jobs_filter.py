"""Shared per-user job filtering logic used by both the Jobs Inbox and the
Analytics overview. Keeping a single source of truth means the dashboard's
"Discovered" stat always matches what's actually visible in the inbox.

Profession-agnostic: this module makes NO assumptions about whether the
user is a Product Manager, AI Engineer, marketer, designer, finance ops,
nurse, accountant, or anything else. It only knows their target_roles +
skills, and matches job titles against those. The semantic embedding
scorer handles relevance ranking after the filter.

Historical note: earlier versions had hardcoded Product Management and
AI/ML title exclusions to fix a specific PM-vs-AI inbox cross-leak when
the user base was just those two professions. Those exclusions actively
hurt users whose roles fell outside the narrow PM/AI regexes (Product
Marketing, ML Ops, Operations, etc.) so they were removed. Cross-leak
prevention now happens via the positive title-keyword filter alone —
if a job title doesn't match any of the user's target roles or skills,
it doesn't enter the inbox in the first place."""

from __future__ import annotations

import re as _re

from sqlalchemy import Text, any_, cast, exists, func, literal, not_, or_
from sqlalchemy.dialects.postgresql import ARRAY, array
from sqlalchemy.orm import aliased

from app.models.job import Job, JobEntity, JobSource
from app.models.scoring import JobScore


# Sentinel the onboarding / profile country picker saves for
# "Worldwide / Remote".
WORLDWIDE_CODE = "WW"

# visa_statuses values meaning the candidate can already work in a country.
_AUTHORIZED_STATUSES = {"citizen", "permanent_resident", "work_visa"}


def work_eligible_countries(home_country: str | None, visa_statuses: dict | None) -> list[str]:
    """Countries the candidate can take a location-restricted role from:
    where they live plus anywhere they're authorized to work."""
    codes = {
        code.upper()
        for code, status in (visa_statuses or {}).items()
        if isinstance(code, str) and status in _AUTHORIZED_STATUSES
    }
    if home_country:
        codes.add(home_country.upper())
    return sorted(codes)


def sponsorship_needed_countries(visa_statuses: dict | None) -> list[str]:
    return sorted(
        code.upper()
        for code, status in (visa_statuses or {}).items()
        if isinstance(code, str) and status == "need_sponsorship"
    )


def country_filter_codes(preferred_countries: list[str] | None) -> list[str] | None:
    """Uppercased country codes to filter on, or None for no country filter.

    Empty preferences and any selection that includes Worldwide both mean
    "don't filter by country". Treating WW as a country code would keep
    only jobs whose location names no real place at all."""
    codes = [c.strip().upper() for c in (preferred_countries or []) if c and c.strip()]
    if not codes or WORLDWIDE_CODE in codes:
        return None
    return codes


def build_role_keywords(target_roles: list[str] | None) -> list[str]:
    """Expand a user's target_roles into SQL LIKE patterns.

    Generates the literal role as a substring match, plus a small set of
    role-family synonyms ONLY for the most common substitutions inside
    the same profession (Manager → Lead / Owner / Director, Engineer →
    Developer). Avoids the over-broad bare-keyword expansions ('% ai %',
    '% pm %') that used to silently pull cross-profession titles into
    every inbox.
    """
    if not target_roles:
        return []

    keywords: set[str] = set()
    for raw in target_roles:
        if not raw:
            continue
        role = raw.strip().lower()
        if not role:
            continue
        # The role itself as a substring (highest-precision match).
        keywords.add(f"%{role}%")
        # Light family expansion: only swap the seniority/leadership word
        # at the END of the role for its common siblings. "Product Manager"
        # picks up "Product Lead" / "Product Director" / "Product Owner",
        # but not unrelated PM jobs at other companies via bare "% pm %".
        # "Marketing Manager" picks up "Marketing Lead" / "Marketing
        # Director". Works the same way for ANY profession.
        SENIORITY_SWAPS = {
            "manager": ["lead", "director", "head", "owner"],
            "lead": ["manager", "director", "head"],
            "director": ["lead", "head", "manager", "vp"],
            "head": ["lead", "director", "manager"],
            "engineer": ["developer"],
            "developer": ["engineer"],
            "analyst": ["specialist", "associate"],
            "specialist": ["analyst", "associate"],
        }
        words = role.split()
        if len(words) >= 2:
            last = words[-1]
            stem = " ".join(words[:-1])
            for swap in SENIORITY_SWAPS.get(last, []):
                keywords.add(f"%{stem} {swap}%")
        # Heading variants: "Head of X" / "X Lead" / "VP of X".
        if len(words) >= 1:
            keywords.add(f"%head of {role}%")
            keywords.add(f"%vp of {role}%")

    return list(keywords)


def _skill_keywords(skills: list[str] | None) -> list[str]:
    """Convert technical/tool skills to SQL LIKE patterns. Skills that are
    too short, too generic, or too noisy as a substring (e.g. 'C', 'go',
    'r') are skipped — they'd match titles like 'Go-to-Market Manager'
    and torpedo precision."""
    if not skills:
        return []
    # Tokens too risky as standalone LIKE patterns. We allow them via
    # full-skill match (e.g. 'r programming') but never as bare '%r%'.
    bad_short = {"c", "r", "go", "ai", "ml", "ui", "ux", "qa", "it"}
    out: list[str] = []
    for raw in skills:
        if not raw:
            continue
        s = raw.strip().lower()
        if len(s) < 3:
            continue
        if s in bad_short:
            continue
        # Drop trailing parenthetical alias like "Workflow Automation (n8n)"
        # → use "workflow automation" + "n8n" separately. The alias is
        # already its own row in candidate_skills (tool category).
        s = _re.sub(r"\s*\(.*?\)\s*", "", s).strip()
        if not s:
            continue
        out.append(f"%{s}%")
    return list(set(out))


async def user_filter_kwargs(db, user_id) -> dict:
    """apply_user_filters arguments from the user's profile, the way the
    inbox passes them (skills are technical and tool skills only)."""
    from sqlalchemy import select
    from app.models.candidate import CandidateProfile, CandidateSkill

    row = (await db.execute(
        select(
            CandidateProfile.id,
            CandidateProfile.target_roles,
            CandidateProfile.blocked_sources,
            CandidateProfile.remote_preference,
            CandidateProfile.preferred_countries,
            CandidateProfile.home_country,
            CandidateProfile.visa_statuses,
            CandidateProfile.salary_min,
            CandidateProfile.salary_currency,
        ).where(CandidateProfile.user_id == user_id)
    )).first()
    if row is None:
        return {"target_roles": None, "user_id": user_id}
    skills = (await db.execute(
        select(CandidateSkill.skill_name).where(
            CandidateSkill.profile_id == row.id,
            CandidateSkill.category.in_(("technical", "tool")),
        )
    )).scalars().all()
    return {
        "target_roles": row.target_roles,
        "skills": [s for s in skills if s],
        "blocked_sources": row.blocked_sources,
        "remote_preference": row.remote_preference,
        "preferred_countries": row.preferred_countries,
        "home_country": row.home_country,
        "visa_statuses": row.visa_statuses,
        "salary_min": row.salary_min,
        "salary_currency": row.salary_currency,
        "user_id": user_id,
    }


def job_group_key(job=Job):
    """Normalized company and title. Postings of the same job for several
    cities, or from several sources, share it; the inbox and the dashboard
    count each job once."""
    return (func.lower(func.trim(job.company)), func.lower(func.trim(job.title)))


def apply_user_filters(
    query,
    *,
    target_roles: list[str] | None,
    skills: list[str] | None = None,
    blocked_sources: list[str] | None = None,
    remote_preference: str | None = None,
    preferred_countries: list[str] | None = None,
    home_country: str | None = None,
    visa_statuses: dict | None = None,
    salary_min: int | None = None,
    salary_currency: str | None = None,
    user_id=None,
):
    """Apply the same filter chain the inbox uses to any Job-based query.

    Pass `user_id` with `skills` so jobs whose scores show a skill match are
    kept even when their title doesn't match.

    The query MUST already join JobSource (left or otherwise) for the
    blocked_sources filter to compile, and JobEntity (outer join) when
    home_country, visa_statuses or salary_min are passed.

    Hard preference filters, each applied only when the job states the
    relevant fact:
      - remote postings restricted to countries the candidate can't work
        from (home_country plus authorized visa_statuses) are hidden;
      - jobs in a country where the candidate needs sponsorship and the
        posting says it doesn't sponsor are hidden;
      - jobs whose top salary is below the candidate's minimum, in the
        same currency, are hidden.

    A job is kept when EITHER its title matches one of the role keywords
    (target_roles + role-family synonyms) OR its title matches one of the
    user's skills/tools. So a 'Python Developer' lands in the inbox of an
    AI Engineer who has Python as a skill, even though 'Python' isn't a
    role keyword.

    When `preferred_countries` names real countries (not empty, and not
    Worldwide — see country_filter_codes), jobs are kept only if they're
    in one of those countries, fully remote (location-agnostic), or have
    no country information at all (NULL — we don't know, give the benefit
    of doubt rather than starve the inbox). Hybrid/onsite jobs in an
    off-target country are dropped here rather than just penalised in
    scoring, so a strong semantic match on a Bangalore role doesn't
    clutter the inbox of someone targeting NL/DE/UK.
    """
    role_keywords = build_role_keywords(target_roles)
    skill_keywords = _skill_keywords(skills)
    title_keywords = list(set(role_keywords + skill_keywords))

    if title_keywords:
        # A job lands in the inbox when:
        #   - its TITLE matches any role keyword OR any skill keyword, OR
        #   - scoring found the user's skills in it (job_scores.skill_score:
        #     the job's extracted skills and its description).
        # Skills only, not role keywords: every description mentions
        # tangentially related roles. Scoring already did the description
        # search; repeating it with LIKE over every description took ~25s
        # per query on the production database.
        # One LIKE ANY over an array, not one LIKE per keyword: with ~90
        # keywords, separate LIKEs lowercase each title ~90 times and took
        # ~1.2s per query on the production database; LIKE ANY took ~0.2s.
        clauses = [func.lower(Job.title).like(any_(literal(sorted(title_keywords), ARRAY(Text))))]
        if skill_keywords and user_id is not None:
            # Aliased: the inbox query already joins job_scores, which
            # would otherwise be correlated away from the subquery.
            scores = aliased(JobScore)
            clauses.append(
                exists().where(
                    scores.job_id == Job.id,
                    scores.user_id == user_id,
                    scores.skill_score > 0,
                )
            )
        query = query.where(or_(*clauses))

    # No hardcoded PM/AI exclusions here. The positive title-keyword
    # match above already gates relevance — if a job title doesn't hit
    # any of the user's role/skill keywords, it's already filtered out.
    # Earlier versions hardcoded "drop all PM titles unless user is a
    # PM" + "drop all AI titles unless user is AI" but those were
    # workarounds for over-broad keyword expansion that no longer
    # exists (build_role_keywords was tightened to stop generating
    # bare '% ai %' / '% pm %' patterns).

    if blocked_sources:
        query = query.where(
            JobSource.name.notin_(blocked_sources) | (JobSource.name.is_(None))
        )

    if preferred_countries:
        wanted = country_filter_codes(preferred_countries)
        if wanted:
            # Keep: full_remote (location-agnostic) OR country in wanted set
            # OR country IS NULL (unclassified — could be anywhere, including
            # the user's preferred regions; dropping these silently torpedos
            # supply since aggregators often omit country on remote postings).
            query = query.where(
                or_(
                    Job.remote_type == "full_remote",
                    func.upper(Job.country).in_(wanted),
                    Job.country.is_(None),
                )
            )

            # Second-pass: catch restricted-remote postings whose country
            # is NULL but whose location text spells out specific countries
            # or cities (e.g. "Brazil, Colombia, Philippines" or "Remote,
            # Bangalore"). Without this, jobs advertised as remote-only-from-
            # India / -LatAm show up for a candidate targeting NL/DE/UK
            # because we set Job.country=NULL on most remote postings.
            #
            # Logic: pull names from BOTH country and city maps. Build the
            # set NOT in the user's preferences and the set that ARE.
            # Drop the job if its location text mentions a non-preferred
            # location AND does not mention any preferred one.
            # Postgres POSIX `~*` with `\y` word boundaries so
            # "Indianapolis" doesn't match `\yindia\y`.
            from app.services.parsing.normalizer import (
                COUNTRY_MAP, CITY_TO_COUNTRY,
            )
            blocked_names: list[str] = []
            preferred_names: list[str] = []
            seen: set[str] = set()
            for name, code in list(COUNTRY_MAP.items()) + list(CITY_TO_COUNTRY.items()):
                lname = name.lower()
                if lname in seen:
                    continue
                seen.add(lname)
                # Skip ambiguous short aliases (uk, uae, u.s.) — they
                # match too aggressively as substrings.
                if len(lname) < 4:
                    continue
                if code.upper() in wanted:
                    preferred_names.append(lname)
                else:
                    blocked_names.append(lname)

            if blocked_names:
                # Postgres POSIX regex; escape special chars in names.
                # Sort longest-first so "new york" matches before "new"
                # would (alternation in POSIX is leftmost-then-longest,
                # but explicit ordering is safest across engines).
                import re as _re
                blocked_names_sorted = sorted(blocked_names, key=len, reverse=True)
                blocked_pattern = (
                    r"\y(" + "|".join(_re.escape(n) for n in blocked_names_sorted) + r")\y"
                )
                blocked_clause = Job.location.op("~*")(blocked_pattern)
                if preferred_names:
                    preferred_names_sorted = sorted(preferred_names, key=len, reverse=True)
                    preferred_pattern = (
                        r"\y(" + "|".join(_re.escape(n) for n in preferred_names_sorted) + r")\y"
                    )
                    preferred_clause = Job.location.op("~*")(preferred_pattern)
                    # Drop if: location mentions blocked AND not preferred.
                    # NULL location passes through (already gated by the
                    # outer country/remote OR-clause above).
                    query = query.where(
                        Job.location.is_(None)
                        | not_(blocked_clause)
                        | preferred_clause
                    )
                else:
                    # No preferred countries match the maps (unlikely);
                    # just drop any blocked-country mention.
                    query = query.where(
                        Job.location.is_(None) | not_(blocked_clause)
                    )
    if remote_preference and remote_preference != "any":
        # Soft remote filter: when the user wants full_remote, also include
        # jobs we couldn't classify ('unknown'). Our classify_remote()
        # heuristic on aggregator location strings is imperfect — at last
        # check 96 of 269 visible jobs were 'unknown' but most are
        # remote-friendly in reality. Excluding them was hiding ~36% of
        # the catalog from the inbox. We accept some hybrid/onsite leakage
        # in exchange for the recall.
        if remote_preference == "full_remote":
            # SQL: NULL fails == comparison and isn't a member of in_(),
            # so we OR an explicit IS NULL.
            query = query.where(
                or_(Job.remote_type == "full_remote", Job.remote_type.is_(None))
            )
        else:
            query = query.where(Job.remote_type == remote_preference)

    # Every hard filter below keeps rows where the job doesn't state the
    # fact (NULL), so missing data never hides a job.
    work_from = work_eligible_countries(home_country, visa_statuses)
    if work_from:
        query = query.where(
            or_(
                JobEntity.eligible_countries.is_(None),
                func.jsonb_array_length(JobEntity.eligible_countries) == 0,
                JobEntity.eligible_countries.op("?|")(cast(array(work_from), ARRAY(Text))),
            )
        )

    needs_sponsorship = sponsorship_needed_countries(visa_statuses)
    if needs_sponsorship:
        query = query.where(
            or_(
                Job.country.is_(None),
                func.upper(Job.country).notin_(needs_sponsorship),
                # IS NOT FALSE is also true for NULL.
                JobEntity.sponsorship_available.is_not(False),
            )
        )

    if salary_min:
        currency = (salary_currency or "USD").upper()
        # Only salaries the source stated (salary_text is set by sources,
        # never by enrichment) can hide a job; extracted ones are too
        # unreliable to filter on.
        query = query.where(
            or_(
                Job.salary_text.is_(None),
                Job.salary_max.is_(None),
                Job.salary_currency.is_(None),
                func.upper(Job.salary_currency) != currency,
                Job.salary_max >= salary_min,
            )
        )
    return query
