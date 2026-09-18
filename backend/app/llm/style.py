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
