"""Shared per-user job filtering logic used by both the Jobs Inbox and the
Analytics overview. Keeping a single source of truth means the dashboard's
"Discovered" stat always matches what's actually visible in the inbox."""

from __future__ import annotations

from sqlalchemy import or_, not_, func

from app.models.job import Job
from app.models.job import JobSource


# Single Postgres POSIX regex (case-insensitive via `~*`) that catches the
# Product Management role family. We use `\y` for word boundaries so:
#   - "Senior PM, AI Platform"      → matches (\ypm\y)
#   - "Lead Product Manager, ML"    → matches (\yproduct\s+manager\y)
#   - "Head of Product, Growth"     → matches
#   - "Product Marketing Manager"   → matches (\yproduct\s+marketing\y)
#   - "Product Operations Lead"     → matches (\yproduct\s+operations\y)
#   - "AI Spammer", "9pm shift"     → does NOT match (word boundary protects)
#
# We exclude this whole family from the inbox unless the user's target roles
# explicitly include "product" — otherwise an AI Engineer search picks up
# "Senior PM, AI Platform" via the generic "% ai " expansion.
_PRODUCT_TITLE_REGEX = (
    r"\y("
    r"product\s+(manager|managers|management|"
    r"lead|leader|leaders|leadership|"
    r"owner|owners|"
    r"strateg\w*|"
    r"director|"
    r"analyst|analytics|"
    r"marketing|"
    r"operations|"
    r"specialist|"
    r"associate)"
    r"|head\s+of\s+product"
    r"|(vp|vice\s+president|director|chief|svp|evp)\s+of\s+product"
    r"|chief\s+product\s+officer|cpo"
    r"|(senior|sr|principal|staff|lead|associate|junior|jr|group|head|technical|tpm)\s+pm"
    r"|pm"
    r")\y"
)


import re as _re

# Matches when the user's TARGET role is actually a PM role (not just any
# role that contains the word "product"). The old check
#   any("product" in r.lower() for r in target_roles)
# was disabling the PM-exclusion filter for users with target_roles like
# "AI Product Engineer" — they'd then see every Senior PM job leak through.
_USER_WANTS_PRODUCT_RE = _re.compile(
    r"\bproduct\s+("
    r"manager|managers|management|"
    r"owner|owners|"
    r"lead|leader|leads|"
    r"director|"
    r"strateg\w*|"
    r"analyst|analytics"
    r")\b"
    r"|\bhead\s+of\s+product\b"
    r"|\b(?:vp|vice\s+president|chief)\s+of\s+product\b"
    r"|\bchief\s+product\s+officer\b"
    r"|\bcpo\b",
    _re.I,
)


def _user_wants_product(target_roles: list[str] | None) -> bool:
    """True only if the user's target_roles list contains an explicit
    Product Management role (PM, Product Owner, Head of Product, etc.).
    Roles that merely contain the word 'product' (e.g. 'AI Product
    Engineer') do NOT count — those are engineering roles and the user
    still wants PM titles excluded from their inbox."""
    if not target_roles:
        return False
    return any(_USER_WANTS_PRODUCT_RE.search(r or "") for r in target_roles)


def build_role_keywords(target_roles: list[str] | None) -> list[str]:
    """Expand a user's target_roles into SQL LIKE patterns. Mirrors the
    behaviour the inbox has used since launch — adding role-family synonyms
    (e.g. "Product Manager" picks up "Product Lead", "Head of Product", etc).
    """
    if not target_roles:
        return []
    keywords: list[str] = []
    for role in target_roles:
        role_lower = role.lower()
        keywords.append(f"%{role_lower}%")
        if "product" in role_lower:
            keywords.extend([
                "%product manager%", "%product lead%", "%product owner%",
                "%head of product%", "%product strateg%", "%product director%",
                "%group product manager%", "%product analyst%",
            ])
        if "ai" in role_lower or "automation" in role_lower or "ml" in role_lower:
            keywords.extend([
                "%ai %", "% ai", "%artificial intelligence%", "%machine learning%",
                "%automation%", "%llm%", "%ml engineer%", "%mlops%",
                "%ai engineer%", "%applied ai%", "%generative ai%",
                "%prompt engineer%", "%workflow%", "%agentic%",
            ])
        if "data" in role_lower:
            keywords.extend(["%data scientist%", "%data analyst%", "%data engineer%"])
        if "design" in role_lower:
            keywords.extend(["%ux design%", "%ui design%", "%product design%"])
    return list(set(keywords))


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
):
    """Apply the same filter chain the inbox uses to any Job-based query.

    The query MUST already join JobSource (left or otherwise) for the
    blocked_sources filter to compile.

    A job is kept when EITHER its title matches one of the role keywords
    (target_roles + role-family synonyms) OR its title matches one of the
    user's skills/tools. So a 'Python Developer' lands in the inbox of an
    AI Engineer who has Python as a skill, even though 'Python' isn't a
    role keyword.
    """
    role_keywords = build_role_keywords(target_roles)
    skill_keywords = _skill_keywords(skills)
    match_keywords = list(set(role_keywords + skill_keywords))
    if match_keywords:
        query = query.where(or_(*[func.lower(Job.title).like(kw) for kw in match_keywords]))

    # Exclude product-management titles unless the user actually targets product.
    # Without this, an AI/ML user gets "Sr. PM, AI Platform" leaking in via the
    # generic "% ai " expansion. `~*` is Postgres' case-insensitive POSIX
    # regex; `\y` gives proper word boundaries so we don't false-positive on
    # things like "9pm shift" or "Spammer".
    if not _user_wants_product(target_roles):
        query = query.where(not_(Job.title.op("~*")(_PRODUCT_TITLE_REGEX)))

    if blocked_sources:
        query = query.where(
            JobSource.name.notin_(blocked_sources) | (JobSource.name.is_(None))
        )
    if remote_preference and remote_preference != "any":
        query = query.where(Job.remote_type == remote_preference)
    return query
