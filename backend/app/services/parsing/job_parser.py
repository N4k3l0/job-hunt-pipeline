import logging

from app.llm.client import llm_client
from app.llm.prompts.parse_job import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, EXTRACT_TOOL

logger = logging.getLogger(__name__)


async def parse_job_text(text: str) -> dict:
    """Parse raw job posting text into structured data using Claude.

    Args:
        text: Raw job posting text (from Firecrawl, API, or manual paste)

    Returns:
        Structured job data dict
    """
    if not text.strip():
        raise ValueError("Empty job text provided")

    prompt = USER_PROMPT_TEMPLATE.format(job_text=text[:15000])  # Limit to avoid token waste

    result = await llm_client.generate_structured(
        task_type="parsing",
        system_prompt=SYSTEM_PROMPT,
        user_prompt=prompt,
        tools=[EXTRACT_TOOL],
    )

    logger.info(
        "Parsed job: %s at %s — %d required skills, %d keywords",
        result.get("title", "unknown"),
        result.get("company", "unknown"),
        len(result.get("required_skills", [])),
        len(result.get("keywords", [])),
    )

    return result
