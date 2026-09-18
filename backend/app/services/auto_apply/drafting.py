"""Draft answers the rules couldn't give, for the user to confirm.

One Claude call per application covers every open question. Drafted
answers are never confirmed: the user reviews each before sending.
"""

from __future__ import annotations

import json
import logging

from app.llm.prompts.draft_application_answers import (
    RECORD_TOOL,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)
from app.llm.style import plain_english
from app.services.auto_apply.answers import answer, normalize_label

logger = logging.getLogger(__name__)

DRAFTABLE_TYPES = {"text", "textarea", "select", "multiselect", "boolean", "number", "url"}
MAX_QUESTIONS = 25
DESCRIPTION_CHARS = 5000


def _question_line(item: dict) -> str:
    entry = {"key": item["key"], "question": item["label"], "type": item["type"]}
    if item.get("description"):
        entry["details"] = item["description"][:600]
    if item.get("options"):
        entry["options"] = [o["label"] for o in item["options"]]
    return json.dumps(entry, ensure_ascii=False)


def to_field_value(item: dict, raw):
    """Convert the model's answer into the field's format, or None if it
    doesn't fit the field (e.g. an option that isn't offered)."""
    if raw is None:
        return None
    if item["type"] in ("select", "multiselect"):
        labels = raw if isinstance(raw, list) else [raw]
        by_label = {normalize_label(o["label"]): o["value"] for o in item.get("options") or []}
        values = [by_label.get(normalize_label(str(l))) for l in labels]
        if not values or None in values:
            return None
        if item["type"] == "select":
            return values[0] if len(values) == 1 else None
        return values
    if isinstance(raw, list):
        raw = raw[0] if len(raw) == 1 else None
        if raw is None:
            return None
    text = str(raw).strip()
    if not text or text.lower() == "null":
        return None
    if item["type"] == "boolean":
        return {"yes": True, "no": False}.get(text.lower())
    if item["type"] == "number":
        try:
            number = float(text.replace(",", ""))
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return text


async def draft_answers(items: list[dict], facts_text: str, job: dict, llm=None) -> dict[str, dict]:
    """Drafted answers for `items`, keyed by field key. Questions the model
    can't answer from the facts are left out."""
    items = [i for i in items if i["type"] in DRAFTABLE_TYPES][:MAX_QUESTIONS]
    if not items:
        return {}
    if llm is None:
        from app.llm.client import llm_client as llm

    prompt = USER_PROMPT_TEMPLATE.format(
        facts=facts_text,
        title=job.get("title") or "",
        company=job.get("company") or "",
        location=job.get("location") or "",
        description=(job.get("description") or "")[:DESCRIPTION_CHARS],
        questions="\n".join(_question_line(i) for i in items),
    )
    result = await llm.generate_structured("applying", SYSTEM_PROMPT, prompt, tools=[RECORD_TOOL], max_tokens=3000)
    by_key = {i["key"]: i for i in items}
    drafted: dict[str, dict] = {}
    for entry in result.get("answers") or []:
        item = by_key.get(entry.get("key"))
        if not item:
            continue
        value = to_field_value(item, entry.get("answer"))
        if isinstance(value, str):
            value = plain_english(value)
        if value is None:
            continue
        basis = (entry.get("basis") or "").strip()
        note = "Drafted from your profile" + (f": {basis}" if basis and basis.lower() != "none" else "") + ". Check it before sending."
        drafted[item["key"]] = answer(value, "drafted", note)
    return drafted
