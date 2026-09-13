"""Find a hiring manager / decision maker for a given job using Claude
with the web_search server tool.

Strategy:
- Ask Claude to search for the most likely person to contact about this
  specific role at this specific company. Priority order: hiring manager
  for the role → department head → recruiter → CEO/founder (small co).
- The model returns a structured `record_contact` tool call with name,
  title, linkedin_url, email_guess, confidence, plus a short justification
  and the citations Claude actually used.
- We swallow web_search citations into a JSONB column so the user can
  click through and verify.

Why not Apollo / Hunter / Clay:
- No new paid API key required (Anthropic's web_search is metered with
  the existing ANTHROPIC_API_KEY).
- A single endpoint covers contact lookup + justification + sources in
  one round-trip.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You help job-seekers find the right person to send a follow-up message to after applying.

For a given role at a given company, identify the single best contact in this priority order:
1. The hiring manager for THIS specific role (e.g. the Engineering Manager who would manage this Senior Engineer).
2. The department head (e.g. VP Product, Head of Engineering).
3. An in-house recruiter at the company who handles this function.
4. For small companies (<50 people), the founder or CEO.

Use the web_search tool. Search the company's LinkedIn page, leadership pages, blog, About pages.
NEVER fabricate. If you cannot find a high-confidence match, return confidence='low' and explain.

When you find someone, call the `record_contact` tool with their details. Always call `record_contact` exactly once, even if you only have a partial match — set the fields you couldn't verify to null and confidence to 'low'."""


RECORD_CONTACT_TOOL = {
    "name": "record_contact",
    "description": "Record the single best decision-maker / hiring contact for the role.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Full name. Null if not found.",
            },
            "title": {
                "type": "string",
                "description": "Job title at the company, e.g. 'VP of Product' or 'Engineering Manager, Platform'.",
            },
            "linkedin_url": {
                "type": "string",
                "description": "Full LinkedIn profile URL (https://www.linkedin.com/in/...). Null if not found.",
            },
            "email_guess": {
                "type": "string",
                "description": "Most likely work email if discoverable from public sources or company patterns (e.g. firstname@company.com when the company uses that pattern). Mark as guess; do NOT fabricate.",
            },
            "confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
                "description": "high = found their name on the company page AND verified they own this function. medium = found name but couldn't fully verify role. low = best guess based on company size / public org chart.",
            },
            "source_notes": {
                "type": "string",
                "description": "1-2 sentences explaining why you picked this person and what you searched.",
            },
        },
        "required": ["confidence", "source_notes"],
    },
}


def _build_user_prompt(company: str, role: str, location: str | None) -> str:
    location_clause = f" The role is based in {location}." if location else ""
    return (
        f"Find the best person to contact about the **{role}** role at **{company}**.{location_clause}\n\n"
        "Use web_search to:\n"
        f"1. Look up '{company} leadership' or '{company} team' to find the org structure.\n"
        f"2. Identify who manages this specific role (e.g. for an Engineering role, find the Engineering Manager / VP Engineering).\n"
        f"3. Find their LinkedIn profile via 'site:linkedin.com/in {company} <their title>'.\n"
        "4. If the company is small (<50 people) and you can't find a hiring manager, fall back to founder / CEO.\n\n"
        "When you have your best answer, call `record_contact` with what you found."
    )


async def find_contact_for_job(
    *,
    company: str,
    role: str,
    location: str | None = None,
    max_searches: int = 5,
) -> dict[str, Any]:
    """Run the web-search-driven lookup. Returns a dict matching the
    record_contact schema, plus a 'citations' list extracted from the
    web_search tool results so the UI can show sources."""
    from app.llm.client import llm_client, model_for, effort_for

    response = await llm_client.client.messages.create(
        model=model_for("search"),
        max_tokens=6000,
        output_config={"effort": effort_for("search")},
        system=SYSTEM_PROMPT,
        tools=[
            {"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches},
            RECORD_CONTACT_TOOL,
        ],
        messages=[{"role": "user", "content": _build_user_prompt(company, role, location)}],
    )

    record: dict[str, Any] | None = None
    citations: list[dict[str, str]] = []

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_contact":
            record = dict(block.input)
        elif getattr(block, "type", None) == "web_search_tool_result":
            for item in getattr(block, "content", []) or []:
                if getattr(item, "type", None) == "web_search_result":
                    citations.append({
                        "url": getattr(item, "url", "") or "",
                        "title": getattr(item, "title", "") or "",
                    })

    if record is None:
        logger.warning(
            "find_contact: model returned no record_contact tool call for %s @ %s",
            role, company,
        )
        record = {
            "name": None,
            "title": None,
            "linkedin_url": None,
            "email_guess": None,
            "confidence": "low",
            "source_notes": "Model did not return a contact record.",
        }

    record["citations"] = citations[:8]  # keep payload bounded
    return record
