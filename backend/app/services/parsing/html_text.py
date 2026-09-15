"""Job description HTML: plain text for matching and excerpts, and safe
HTML for showing a description on the job page.

Descriptions come from job boards and scrapers, so their HTML can't be
trusted. Only safe_description_html's output may be rendered as HTML."""

import html
import re

import nh3

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_REAL_TAG_RE = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
# `&lt;p` or, escaped twice, `&amp;lt;p`.
_ESCAPED_TAG_RE = re.compile(r"&(?:amp;)?lt;\s*/?\s*[a-zA-Z]")
_BLANK_LINE_RE = re.compile(r"\n\s*\n")

# Formatting only: no images, forms, frames, styles or scripts.
_ALLOWED_TAGS = {
    "p", "br", "hr", "div", "span", "section",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "b", "em", "i", "u", "small", "sub", "sup",
    "ul", "ol", "li", "dl", "dt", "dd",
    "blockquote", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "a",
}
# Removed together with everything inside them.
_DROPPED_WITH_CONTENT = {"script", "style", "iframe", "noscript", "template", "object", "embed", "svg", "math"}
_SANITIZER = nh3.Cleaner(
    tags=_ALLOWED_TAGS,
    clean_content_tags=_DROPPED_WITH_CONTENT,
    attributes={"a": {"href"}},
    url_schemes={"http", "https", "mailto"},
    url_relative="deny",
    link_rel="noopener noreferrer nofollow",
    set_tag_attribute_values={"a": {"target": "_blank"}},
    strip_comments=True,
)


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


def safe_description_html(raw: str | None) -> str | None:
    """Sanitized HTML for a job description, or None when there's none.

    Escaped HTML is decoded first so it shows formatted rather than as
    markup, and plain text keeps its paragraphs and line breaks."""
    text = (raw or "").strip()
    if not text:
        return None
    for _ in range(2):
        if _REAL_TAG_RE.search(text) or not _ESCAPED_TAG_RE.search(text):
            break
        text = html.unescape(text)
    if not _REAL_TAG_RE.search(text):
        paragraphs = [p.strip() for p in _BLANK_LINE_RE.split(text) if p.strip()]
        text = "".join(
            "<p>" + html.escape(html.unescape(p)).replace("\n", "<br>") + "</p>" for p in paragraphs
        )
    return _SANITIZER.clean(text).strip() or None
