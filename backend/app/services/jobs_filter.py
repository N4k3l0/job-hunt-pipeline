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

from sqlalchemy import or_, not_, func

from app.models.job import Job
from app.models.job import JobSource


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


def apply_user_filters(
    query,
    *,
    target_roles: list[str] | None,
    skills: list[str] | None = None,
    blocked_sources: list[str] | None = None,
    remote_preference: str | None = None,
    preferred_countries: list[str] | None = None,
):
    """Apply the same filter chain the inbox uses to any Job-based query.

    The query MUST already join JobSource (left or otherwise) for the
    blocked_sources filter to compile.

    A job is kept when EITHER its title matches one of the role keywords
    (target_roles + role-family synonyms) OR its title matches one of the
    user's skills/tools. So a 'Python Developer' lands in the inbox of an
    AI Engineer who has Python as a skill, even though 'Python' isn't a
    role keyword.

    When `preferred_countries` is non-empty, jobs are kept only if they're
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
        #   - its DESCRIPTION mentions any of the user's skills.
        # Description matching is restricted to SKILLS only (not role
        # keywords) — matching role keywords against description is too
        # noisy because every JD mentions tangentially-related terms.
        # Specific skill tokens (Python, n8n, Excel, Figma, SQL...) are
        # high-signal: if a JD mentions them, the role probably uses them.
        clauses = [func.lower(Job.title).like(kw) for kw in title_keywords]
        if skill_keywords:
            clauses.extend(
                func.lower(Job.raw_description).like(kw) for kw in skill_keywords
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
        wanted = [c.upper() for c in preferred_countries if c]
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
    return query
