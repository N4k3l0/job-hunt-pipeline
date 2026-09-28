"""How everything the app writes for a user should read.

One rule, in one place: plain English that sounds like the person, not
like a model. The prompt asks for it; `plain_english` enforces the part a
model still slips on, mainly em dashes.
"""

import hashlib
import json
import logging
import re

logger = logging.getLogger(__name__)

STYLE_RULES = """## How to write it (strict)
- Plain, simple English. Short sentences. Say it the way a person would say it out loud.
- No em dashes or en dashes (- and -). Use a comma, a full stop, brackets or a plain hyphen.
- No words people don't use in conversation: delve, leverage, tapestry, robust, spearheaded,
  seamless, cutting-edge, passionate, thrilled, excited to, landscape, realm, testament,
  underscore, pivotal, myriad, embark, elevate, unlock, journey.
- No throat-clearing ("I am writing to", "I would like to express"), no filler adjectives,
  no summarising what you just said.
- Active voice. First person where it's the candidate speaking.
- Say the concrete thing: what was built, for whom, what happened."""

_DASHES = "—–‒−"
_BETWEEN_DIGITS = re.compile(rf"(?<=\d)\s*[{_DASHES}]\s*(?=\d)")
_SPACED = re.compile(rf"\s*[{_DASHES}]\s*")
_QUOTES = {"‘": "'", "’": "'", "“": '"', "”": '"', "…": "..."}


_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")


def _undash_sentence(match: re.Match) -> str:
    # A pair of dashes sets words apart, like commas do. A single dash
    # joins two thoughts, which read better as two sentences: a comma there
    # made run-ons like "it runs as an agent, it looks up managers".
    sentence = match.group(0)
    if len(_SPACED.findall(sentence)) != 1:
        return _SPACED.sub(", ", sentence)
    before, after = _SPACED.split(sentence, maxsplit=1)
    if not after or after[:1] in ",.;:!?":
        return before.rstrip() + after
    if not before.strip():
        return after
    return f"{before.rstrip()}. {after[:1].upper()}{after[1:]}"


def plain_english(text: str | None) -> str:
    """Take the dashes and typographic quotes out of written text, as a last
    resort: `without_dashes` has the model rewrite those sentences first. A
    range of numbers keeps a plain hyphen, a pair of dashes becomes commas,
    and a single dash ends the sentence."""
    if not text:
        return text or ""
    cleaned = _BETWEEN_DIGITS.sub("-", text)
    cleaned = _SENTENCE.sub(_undash_sentence, cleaned)
    for bad, good in _QUOTES.items():
        cleaned = cleaned.replace(bad, good)
    # A dash before punctuation leaves a comma that shouldn't be there.
    cleaned = re.sub(r",\s*([,.;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


# ─── Checking writing that goes out ──────────────────────────────────────────
# What an application sends has to read like STYLE_RULES says, whoever
# wrote it: answers the user typed or pasted are checked the same way as
# ones the app wrote.

# The words STYLE_RULES bans, plus a few more, with what people say instead.
AVOID_WORDS = {
    "delve": "look into", "delves": "looks into", "delved": "looked into",
    "leverage": "use", "leveraged": "used", "leveraging": "using",
    "utilize": "use", "utilized": "used", "utilizing": "using", "utilise": "use",
    "tapestry": None, "robust": "strong", "seamless": "smooth", "seamlessly": "smoothly",
    "spearhead": "lead", "spearheaded": "led", "spearheading": "leading",
    "cutting-edge": "new", "passionate": None, "thrilled": "glad",
    "landscape": None, "realm": None, "testament": None,
    "underscore": "show", "underscores": "shows", "pivotal": "key", "myriad": "many",
    "embark": "start", "elevate": "improve", "unlock": None, "synergy": None,
    "journey": None,
}
STIFF_OPENINGS = (
    "i am writing to", "i'm writing to", "i would like to express", "i am thrilled",
    "i am excited to", "i'm excited to",
)
LONG_SENTENCE_WORDS = 40

_WORD = re.compile(r"[a-z][a-z'-]*")
_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def has_dashes(text: str | None) -> bool:
    return bool(text) and any(d in text for d in _DASHES)


def writing_problems(text: str | None) -> list[str]:
    """What to change so the text reads like a person wrote it, in words
    the user can act on. Empty when it's fine."""
    if not text or not text.strip():
        return []
    problems = []
    if has_dashes(text):
        problems.append("It has a long dash. Use a comma or a full stop instead.")
    lowered = text.lower()
    seen = set()
    for word in _WORD.findall(lowered):
        if word in AVOID_WORDS and word not in seen:
            seen.add(word)
            instead = AVOID_WORDS[word]
            problems.append(
                f"It uses \"{word}\", which people don't say out loud."
                + (f" Try \"{instead}\"." if instead else "")
            )
    for opening in STIFF_OPENINGS:
        if opening in lowered:
            problems.append(f"It says \"{opening[0].upper()}{opening[1:]}\". Say the point straight away.")
            break
    longest = max((len(s.split()) for s in _SENTENCES.split(text.strip())), default=0)
    if longest > LONG_SENTENCE_WORDS:
        problems.append(f"One sentence is {longest} words long. Split it up.")
    return problems


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ─── Fixing and reading through, with a model ───────────────────────────────

DASH_FIX_SYSTEM = (
    "Rewrite only the sentences in this text that contain a long dash (\u2014 or \u2013) so they have none, "
    "the way a person would write them: a full stop, a colon, brackets, or different words. Leave every "
    "other sentence exactly as it is, line breaks included. Return the whole text and nothing else."
)


async def without_dashes(text: str | None, llm=None) -> str:
    """The text without long dashes. The sentences that have one are
    rewritten by the model, since swapping a dash for a comma made run-on
    sentences; `plain_english` is the fallback."""
    if not has_dashes(text):
        return plain_english(text)
    try:
        if llm is None:
            from app.llm.client import llm_client as llm
        rewritten = (await llm.generate(
            "review", DASH_FIX_SYSTEM, text, max_tokens=len(text) // 2 + 400,
        )).strip()
        if rewritten and len(rewritten) > len(text) // 2:
            return plain_english(rewritten)
    except Exception as e:  # noqa: BLE001 — the fallback still takes the dashes out
        logger.warning("Couldn't rewrite the dashes out, falling back: %s", e)
    return plain_english(text)


READ_THROUGH_SYSTEM = (
    "You read what a person is about to send with a job application, the way a careful friend would, and "
    "point out what to change so it sounds like them talking. Flag only real problems:\n"
    "- jargon or buzzwords a person wouldn't say out loud (a technical term the job itself uses, used "
    "plainly, is fine)\n"
    "- run-on sentences: two complete sentences joined only by a comma\n"
    "- stiff, corporate or salesy phrasing, and inflated claims\n"
    "- phrases lifted from the job ad instead of said in their own words\n"
    "- anything else that reads like a machine wrote it\n"
    "Go through it one sentence at a time before deciding. At most eight, the clearest first. Quote the "
    "exact words (under 12) and say in plain English what to do instead.\n"
    "Mark a problem serious only when it clearly breaks these rules. Matters of taste, small polish and "
    "anything you'd call minor are not serious. On a resume, short clipped lines without \"I\" are normal, "
    "so don't flag them for that. If it's fine to send, record no problems.\n\n" + STYLE_RULES
)

READ_THROUGH_TOOL = {
    "name": "record_problems",
    "description": "Record what to change, or nothing if it reads fine.",
    "input_schema": {
        "type": "object",
        "properties": {
            "problems": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {"type": "string", "description": "The exact words, under 12"},
                        "fix": {"type": "string", "description": "What to do instead, in plain English"},
                        "serious": {"type": "boolean", "description": "It clearly breaks the rules, not a matter of taste"},
                    },
                    "required": ["quote", "fix", "serious"],
                },
            },
        },
        "required": ["problems"],
    },
}

NOT_READ_YET = "The app hasn't read this through yet."
# Saved findings carry this; changing how the reviewer reads (the prompt,
# what counts) means bumping it, so everything is read again.
READ_THROUGH_VERSION = 2


def read_is_current(read: dict | None, text: str) -> bool:
    """Whether saved findings are for these exact words, by today's reviewer."""
    read = read or {}
    return read.get("fp") == fingerprint(text) and read.get("v") == READ_THROUGH_VERSION


def saved_read(text: str, problems: list[str]) -> dict:
    return {"fp": fingerprint(text), "v": READ_THROUGH_VERSION, "problems": problems}


async def read_through(text: str, *, what: str, llm=None) -> list[str]:
    """What a careful reader would change, each quoting the words. Raises
    if the model can't be asked (for example, AI is paused), so the caller
    knows the text wasn't read."""
    if llm is None:
        from app.llm.client import llm_client as llm
    result = await llm.generate_structured(
        "review", READ_THROUGH_SYSTEM, f"This is {what}:\n\n{text}",
        tools=[READ_THROUGH_TOOL], max_tokens=1200,
    )
    return _problems_from(result.get("problems"))


def _problems_from(raw) -> list[str]:
    """The model's findings as sentences. It usually sends quote and fix
    pairs, but sometimes plain strings, or the list as a JSON string."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = [raw]
    problems = []
    for item in (raw if isinstance(raw, list) else [])[:8]:
        if isinstance(item, dict):
            # Only clear problems stand in the way of sending. A reviewer
            # always finds something, and taste isn't a reason to wait.
            if item.get("serious") is False:
                continue
            quote, fix = (item.get("quote") or "").strip(), plain_english((item.get("fix") or "").strip())
            if quote and fix:
                problems.append(f"\"{quote}\": {fix}")
        elif isinstance(item, str) and item.strip():
            problems.append(plain_english(item.strip()))
    return problems


REVISE_TOOL = {
    "name": "record_revision",
    "description": "Record the revised lines, the same number as given, in the same order.",
    "input_schema": {
        "type": "object",
        "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
        "required": ["lines"],
    },
}


async def revise_plainly(lines: list[str], problems: list[str], *, what: str, llm=None) -> list[str]:
    """The lines rewritten to fix what the read-through found: every fact,
    name and number kept, nothing added, the same number of lines. Lines
    come back unchanged if the model's answer doesn't fit."""
    if not problems or not lines:
        return lines
    if llm is None:
        from app.llm.client import llm_client as llm
    numbered = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))
    listed = "\n".join(f"- {p}" for p in problems)
    prompt = (
        f"This is {what}, one numbered line each:\n\n{numbered}\n\n"
        f"A careful reader wants these changed:\n{listed}\n\n"
        "Rewrite the lines to fix them, so they sound like the person talking. Keep every fact, name and "
        "number, and add nothing new. Lines with nothing to fix stay exactly as they are. Return the same "
        f"number of lines ({len(lines)}), in the same order, without the numbers."
    )
    result = await llm.generate_structured("review", STYLE_RULES, prompt, tools=[REVISE_TOOL], max_tokens=3000)
    revised = result.get("lines")
    if not isinstance(revised, list) or len(revised) != len(lines) or not all(isinstance(x, str) for x in revised):
        return lines
    return [plain_english(re.sub(r"^\s*\d+\.\s+", "", x).strip()) or old for x, old in zip(revised, lines)]
