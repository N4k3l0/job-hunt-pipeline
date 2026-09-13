"""Profession-agnostic match signals between a job and a candidate.

Each function returns a 0..1 value plus the details worth showing the
user. Nothing here knows about specific professions: titles are compared
by their core words, skills by normalized names, seniority by level words
and years of experience.

A full rescore runs these for every job in the catalog, so candidate-side
work (skill sets, title words, years of experience) is cached, and each
job's text is normalized once and searched with plain substring checks.
"""

from __future__ import annotations

import re
from datetime import date
from functools import lru_cache

# Words that describe level rather than the role itself.
# "Assistant" is left out: it's the role in "Medical Assistant".
_LEVEL_WORDS = {
    "senior", "sr", "junior", "jr", "principal", "staff", "associate",
    "intern", "internship", "trainee", "graduate", "entry",
    "mid", "level", "i", "ii", "iii", "iv", "v", "1", "2", "3", "4",
}
_STOP_WORDS = {
    "of", "the", "and", "for", "at", "in", "with", "to", "a", "an", "or",
    "remote", "hybrid", "onsite", "contract", "contractor", "temporary",
    "full", "part", "time", "fulltime", "parttime", "m", "f", "d", "w",
    "x", "all", "genders", "new", "urgent", "hiring", "job",
}
# Leadership words are interchangeable enough that a "Marketing Lead"
# search should still surface "Marketing Manager".
_LEADERSHIP = {"manager", "lead", "head", "director", "owner", "supervisor", "chief"}
_ABBREVIATIONS = {
    "mgr": "manager", "eng": "engineer", "engr": "engineer", "dev": "developer",
    "admin": "administrator", "exec": "executive", "rep": "representative",
    "coord": "coordinator", "spec": "specialist", "tech": "technician",
    "acct": "accountant", "hr": "human resources",
}
_SUFFIX_NORMALIZE = {
    "engineering": "engineer", "development": "developer", "management": "manager",
    "accounting": "accountant", "nursing": "nurse", "teaching": "teacher",
    "analytics": "analyst", "design": "designer",
}

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")
_NON_WORD_RE = re.compile(r"[^a-z0-9+#]+")
_PAREN_RE = re.compile(r"\(([^)]*)\)")

SENIORITY_LEVELS = ["entry", "mid", "senior", "lead", "director", "vp", "c_level"]

# Only the start of a description is searched for skill mentions.
DESCRIPTION_SEARCH_CHARS = 6000


def _stem(token: str) -> str:
    token = _SUFFIX_NORMALIZE.get(token, token)
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    return token


@lru_cache(maxsize=8192)
def title_tokens(title: str | None) -> frozenset[str]:
    """Core role words of a title, without level words or filler."""
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall((title or "").lower()):
        tokens.extend(_ABBREVIATIONS.get(raw, raw).split())
    return frozenset(
        _stem(t) for t in tokens
        if t not in _LEVEL_WORDS and t not in _STOP_WORDS and len(t) > 1
    )


def _token_overlap(wanted: frozenset[str], have: frozenset[str]) -> float:
    """Weighted count of `wanted` tokens found in `have`; leadership words
    match each other at 0.8."""
    score = 0.0
    have_leadership = bool(have & _LEADERSHIP)
    for token in wanted:
        if token in have:
            score += 1.0
        elif have_leadership and token in _LEADERSHIP:
            score += 0.8
    return score


def title_similarity(role: str, job_title: str) -> float:
    wanted = title_tokens(role)
    have = title_tokens(job_title)
    if not wanted or not have:
        return 0.0
    coverage = _token_overlap(wanted, have) / len(wanted)
    precision = _token_overlap(have, wanted) / len(have)
    return min(1.0, 0.75 * coverage + 0.25 * precision)


def title_match(
    job_title: str,
    target_roles: list[str] | None,
    recent_titles: list[str] | None = None,
    interests: list[str] | None = None,
) -> tuple[float, str | None]:
    """Best similarity between the job title and the roles the candidate
    wants. Their search keywords (interests) and recent job titles count
    too, at a discount, so a profile without target roles still gets a
    sensible title signal."""
    candidates = (
        [(role, 1.0) for role in target_roles or []]
        + [(kw, 0.9) for kw in interests or []]
        + [(title, 0.8) for title in (recent_titles or [])[:3]]
    )
    if not candidates:
        return 0.5, None
    best, best_role = 0.0, None
    for phrase, weight in candidates:
        s = weight * title_similarity(phrase, job_title)
        if s > best:
            best, best_role = s, phrase
    return round(best, 3), best_role


def normalize_skill(skill: str) -> str:
    return _NON_WORD_RE.sub(" ", skill.lower()).strip()


def padded_text(text: str | None) -> str:
    """Normalized text with spaces at both ends, so `f" {phrase} " in it`
    is a whole-word phrase search."""
    return f" {_NON_WORD_RE.sub(' ', (text or '').lower()).strip()} "


@lru_cache(maxsize=512)
def _candidate_skill_index(skills: tuple[str, ...]) -> tuple[frozenset[str], tuple[tuple[str, frozenset[str]], ...]]:
    out: set[str] = set()
    for raw in skills:
        if not raw:
            continue
        for alias in _PAREN_RE.findall(raw):
            a = normalize_skill(alias)
            if len(a) >= 2:
                out.add(a)
        base = normalize_skill(_PAREN_RE.sub(" ", raw))
        if len(base) >= 2:
            out.add(base)
    return frozenset(out), tuple((c, frozenset(c.split())) for c in sorted(out))


def expand_skills(skills: list[str] | None) -> set[str]:
    """Normalized skill names, with parenthetical aliases split out
    ('Workflow Automation (n8n)' gives both)."""
    return set(_candidate_skill_index(tuple(skills or ()))[0])


@lru_cache(maxsize=65536)
def _skill_matches(job_skill: str, candidate_key: tuple[str, ...]) -> bool:
    names, entries = _candidate_skill_index(candidate_key)
    if job_skill in names:
        return True
    padded_job = f" {job_skill} "
    job_words = frozenset(job_skill.split())
    for c, c_words in entries:
        # Whole-phrase containment ("python" in "python 3") or strong word
        # overlap for multi-word skills ("financial modeling" ~ "financial modeling and forecasting").
        if len(c) >= 3 and f" {c} " in padded_job:
            return True
        if len(job_skill) >= 3 and f" {job_skill} " in f" {c} ":
            return True
        if len(job_words) > 1 and len(c_words) > 1:
            if len(job_words & c_words) / min(len(job_words), len(c_words)) >= 0.6:
                return True
    return False


def skill_match(
    job_skills: list[str] | None,
    job_description: str | None,
    candidate_skills: list[str] | None,
    nice_to_have: list[str] | None = None,
) -> tuple[float, list[str], list[str]]:
    """Share of the job's skills the candidate has, blended with how many
    of the candidate's skills the description mentions. Returns
    (score, matched, missing)."""
    candidate_key = tuple(candidate_skills or ())
    names, _ = _candidate_skill_index(candidate_key)
    if not names:
        return 0.5, [], []

    required = list(dict.fromkeys(
        s for s in (normalize_skill(x) for x in (job_skills or []) if x) if s
    ))[:25]
    optional = [s for s in (normalize_skill(x) for x in (nice_to_have or []) if x) if s]

    description = padded_text((job_description or "")[:DESCRIPTION_SEARCH_CHARS])
    mentioned = [c for c in names if len(c) >= 3 and f" {c} " in description]
    mention_signal = min(1.0, len(mentioned) / 5)

    if not required:
        return round(0.85 * mention_signal, 3), sorted(mentioned)[:10], []

    matched = [s for s in required if _skill_matches(s, candidate_key)]
    missing = [s for s in required if s not in matched]
    coverage = len(matched) / len(required)
    optional_bonus = 0.0
    if optional:
        optional_bonus = 0.1 * (sum(1 for s in optional if _skill_matches(s, candidate_key)) / len(optional))
    score = min(1.0, 0.8 * coverage + 0.2 * mention_signal + optional_bonus)
    return round(score, 3), matched[:10], missing[:10]


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


@lru_cache(maxsize=1024)
def _years_from_spans(spans: tuple[tuple[str | None, str | None], ...], today: date) -> float:
    ranges: list[tuple[date, date]] = []
    for start_raw, end_raw in spans:
        start = _parse_date(start_raw)
        if start is None:
            continue
        end = _parse_date(end_raw) or today
        if end > start:
            ranges.append((start, end))
    total_days = 0
    current_start = current_end = None
    for start, end in sorted(ranges):
        if current_end is None or start > current_end:
            if current_end is not None:
                total_days += (current_end - current_start).days
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total_days += (current_end - current_start).days
    return round(total_days / 365.25, 1)


def candidate_years(work_history: list[dict] | None, today: date | None = None) -> float:
    """Years of experience, counting overlapping jobs once."""
    spans = tuple(
        (str(e.get("start_date")) if e.get("start_date") else None,
         str(e.get("end_date")) if e.get("end_date") else None)
        for e in (work_history or [])
    )
    return _years_from_spans(spans, today or date.today())


def level_from_title(title: str | None) -> str | None:
    t = f" {(title or '').lower()} "
    if re.search(r"\b(chief|cto|ceo|cfo|coo|cmo|cpo)\b", t):
        return "c_level"
    if re.search(r"\b(vp|vice president)\b", t):
        return "vp"
    if re.search(r"\b(director|head of)\b", t):
        return "director"
    # "Manager" is left out: in most professions it names the role, not
    # a level above senior.
    if re.search(r"\b(lead|principal|staff)\b", t):
        return "lead"
    if re.search(r"\b(senior|sr)\b", t):
        return "senior"
    if re.search(r"\b(junior|jr|intern|graduate|entry|trainee)\b", t):
        return "entry"
    return None


def level_from_years(years: float) -> str:
    # Years alone never imply lead or director — plenty of people stay
    # individual contributors. Those levels come from titles.
    if years >= 6:
        return "senior"
    if years >= 2:
        return "mid"
    return "entry"


def seniority_match(
    job_seniority: str | None,
    job_title: str,
    years_required_min: int | None,
    work_history: list[dict] | None,
) -> tuple[float, dict]:
    years = candidate_years(work_history)
    candidate_level = None
    if work_history:
        candidate_level = level_from_title(work_history[0].get("title")) or level_from_years(years)

    job_level = job_seniority if job_seniority in SENIORITY_LEVELS else level_from_title(job_title)
    if job_level is None and years_required_min is not None:
        job_level = level_from_years(years_required_min)

    detail = {"job_level": job_level, "candidate_level": candidate_level, "candidate_years": years}
    if job_level is None or candidate_level is None:
        return 0.55, detail

    diff = abs(SENIORITY_LEVELS.index(job_level) - SENIORITY_LEVELS.index(candidate_level))
    score = {0: 1.0, 1: 0.7, 2: 0.35}.get(diff, 0.1)
    if years_required_min is not None and years + 1 < years_required_min:
        score = min(score, 0.4)
    return score, detail


def domain_match(job_text: str, domain_tags: list[str] | None) -> tuple[float, list[str]]:
    tags = {normalize_skill(t) for t in (domain_tags or []) if t and len(t.strip()) >= 3}
    tags.discard("")
    if not tags:
        return 0.5, []
    text = padded_text(job_text[:DESCRIPTION_SEARCH_CHARS])
    hits = sorted(t for t in tags if f" {t} " in text)
    return min(1.0, len(hits) / 2), hits[:5]
