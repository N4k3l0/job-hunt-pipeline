"""Shared per-user job filtering logic used by both the Jobs Inbox and the
Analytics overview. Keeping a single source of truth means the dashboard's
"Discovered" stat always matches what's actually visible in the inbox."""

from __future__ import annotations

from sqlalchemy import or_, func

from app.models.job import Job
from app.models.job import JobSource


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


def apply_user_filters(
    query,
    *,
    target_roles: list[str] | None,
    blocked_sources: list[str] | None,
    remote_preference: str | None,
):
    """Apply the same filter chain the inbox uses to any Job-based query.

    The query MUST already join JobSource (left or otherwise) for the
    blocked_sources filter to compile.
    """
    role_keywords = build_role_keywords(target_roles)
    if role_keywords:
        query = query.where(or_(*[func.lower(Job.title).like(kw) for kw in role_keywords]))
    if blocked_sources:
        query = query.where(
            JobSource.name.notin_(blocked_sources) | (JobSource.name.is_(None))
        )
    if remote_preference and remote_preference != "any":
        query = query.where(Job.remote_type == remote_preference)
    return query
