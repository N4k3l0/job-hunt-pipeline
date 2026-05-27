"""Translate non-English job titles to English at ingest time.

One Anthropic Haiku call per title — cheapest model, fast, ~$0.00001
per call. The prompt asks Claude to detect the language and either
translate or return the original unchanged.

Output contract:
- Returns `(title_en, language)` tuple.
- `title_en` is `None` when the title is already English (signal to
  the caller to leave `Job.title_en` NULL and avoid storing a
  duplicate).
- `language` is an ISO 639-1 code in lowercase ("en", "de", "nl",
  "fr", "es", etc.). Falls back to "en" when detection fails, so
  the inbox never hides a job just because translation errored.

Failure-mode: any exception (rate limit, API error, parsing) is
caught and the call returns `(None, None)` so the caller can decide
to keep the original title untouched without blocking ingest.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Tuple

from app.llm.client import llm_client

logger = logging.getLogger(__name__)


_PROMPT = """\
You are a job-title translator for an English-language job board.

Given the title below, determine:
1. The source language (ISO 639-1 lowercase: en, de, nl, fr, es, it, pt, pl, etc.)
2. The English translation, if needed.

If the title is already in clear English, return the original unchanged.
If the title is in another language OR mixes languages, return a clean English translation.
Keep brand names, company names, and acronyms intact (e.g. "SAP", "AWS").
Don't add or remove information. Don't change capitalization style.
Return ONLY a JSON object on a single line with two keys: "language" and "title_en".

Title: {title}
"""


_JSON_LINE_RE = re.compile(r"\{[^{}]*\"language\"[^{}]*\}", re.S)


async def translate_title_to_english(title: str) -> Tuple[str | None, str | None]:
    """Detect language + translate a job title.

    Returns:
        (translated, language) where:
        - translated is None when the source title is already English
          (the caller should NOT store it — let the Job.title_en column
          stay NULL so the frontend just displays Job.title).
        - language is the detected ISO 639-1 code, or None on failure.
    """
    if not title or not title.strip():
        return (None, None)

    try:
        response = await llm_client.client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": _PROMPT.format(title=title.strip())}],
        )
        raw = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("title translation failed for %r: %s", title[:60], e)
        return (None, None)

    # Haiku usually returns clean JSON; defend against accidental
    # ```json fences or trailing prose by extracting the first
    # {...} object that contains "language".
    payload = raw
    if not payload.startswith("{"):
        m = _JSON_LINE_RE.search(raw)
        if not m:
            logger.warning("title translation returned non-JSON for %r: %r", title[:60], raw[:120])
            return (None, None)
        payload = m.group(0)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("title translation JSON parse failed for %r: %r", title[:60], payload[:120])
        return (None, None)

    language = (data.get("language") or "").strip().lower() or None
    translated = (data.get("title_en") or "").strip() or None

    # Language already English → don't store a duplicate, even if the
    # model echoed it back. Same when the translation equals the input
    # case-insensitively (English-Latin titles like "Senior Engineer").
    if language == "en":
        return (None, "en")
    if translated and translated.lower() == title.strip().lower():
        return (None, language or "en")

    return (translated, language)


_DESCRIPTION_PROMPT = """\
You are translating a job description for an English-language job board.

Translate the description below into clear, natural English.

Rules:
- Preserve the original structure (paragraphs, bullet points, line breaks).
- Keep brand names, company names, acronyms, and technical terms unchanged
  (Python, SAP, AWS, React, GraphQL, Kubernetes, etc.).
- Don't add or remove content. Don't summarise. Don't add a preamble or
  closing remark.
- If the description is already entirely in English, return it unchanged.
- Return ONLY the translated text. No commentary.

Description:
{description}
"""

# Cap input size to keep Haiku response time predictable and avoid
# blowing the per-ingest budget on a single mega-description. Anything
# longer gets truncated; the translated version is still better than
# the German original for triage.
DESCRIPTION_INPUT_CAP = 8000


async def translate_description_to_english(
    description: str | None,
    source_language: str | None,
) -> str | None:
    """Translate a long job description to English.

    Returns the translated text, or None when:
    - the input is empty / whitespace
    - source_language is already "en" (caller should skip the call)
    - Haiku fails / returns empty
    - the translation came back identical to the input (already English)

    Caller stores the return value on `Job.raw_description_en` and the
    frontend renders `raw_description_en || raw_description` so a None
    result simply falls through to the original.
    """
    if not description or not description.strip():
        return None
    if source_language == "en":
        return None

    text = description.strip()[:DESCRIPTION_INPUT_CAP]

    try:
        response = await llm_client.client.messages.create(
            model="claude-haiku-4-5",
            # Output cap roughly mirrors the input cap — translations
            # are usually similar length to the source, plus a little
            # headroom for languages that expand (e.g. German → English
            # often grows by ~5%).
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": _DESCRIPTION_PROMPT.format(description=text),
            }],
        )
        translated = "".join(
            getattr(block, "text", "")
            for block in response.content
            if getattr(block, "type", "") == "text"
        ).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "description translation failed (source_lang=%s, len=%d): %s",
            source_language, len(text), e,
        )
        return None

    if not translated:
        return None
    if translated.lower() == text.lower():
        return None
    return translated
