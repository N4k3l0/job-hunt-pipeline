"""How everything the app writes for a user should read.

One rule, in one place: plain English that sounds like the person, not
like a model. The prompt asks for it; `plain_english` enforces the part a
model still slips on, mainly em dashes.
"""

import re

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


def plain_english(text: str | None) -> str:
    """Take the dashes and typographic quotes out of written text. A range
    of numbers keeps a plain hyphen; anywhere else a dash becomes a comma,
    which is how people write."""
    if not text:
        return text or ""
    cleaned = _BETWEEN_DIGITS.sub("-", text)
    cleaned = _SPACED.sub(", ", cleaned)
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
