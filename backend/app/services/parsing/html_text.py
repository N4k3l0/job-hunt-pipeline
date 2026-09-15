"""Plain text from job description HTML."""

import html
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(raw: str | None) -> str:
    """Remove tags and decode entities, keeping line breaks.

    About a fifth of stored descriptions hold their HTML escaped
    (`&lt;p&gt;`), a few of them twice. Decoding turns those into tags, so
    tags are stripped again after each decode."""
    text = _HTML_TAG_RE.sub(" ", raw or "")
    for _ in range(2):
        if "&" not in text:
            break
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = _HTML_TAG_RE.sub(" ", decoded)
    return text
