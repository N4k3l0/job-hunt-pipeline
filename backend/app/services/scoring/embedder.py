"""Voyage AI embeddings for semantic job scoring.

Used to replace the rule-based title + skill + industry buckets in the
inbox scorer. Each job + profile gets a 512-dim vector; scoring becomes
a cosine similarity between them, which catches matches the keyword-
based path misses ('AI Workflow Lead' ↔ 'AI Engineer', paraphrased
bullets, etc.).

Costs ~\$0.02 per million tokens (voyage-3-lite). One full pass over a
1.7 k-job catalogue ≈ \$0.17 in one-time embed cost. Per-resume changes
are ~\$0.0002. Negligible vs. the LLM calls the app already makes.
"""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# 512-dim is enough for this size catalogue and cheaper to store.
# Trade-off: voyage-3 (1024-dim) gives ~3% better retrieval at 3× the
# token cost. For an inbox of ~2 k jobs and a small user base, 512 is
# the right call.
EMBEDDING_MODEL = "voyage-3-lite"
EMBEDDING_DIM = 512

# Voyage's API accepts batches of up to 128 strings.
MAX_BATCH = 128

_VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"


async def embed_texts(
    texts: Sequence[str],
    *,
    input_type: str = "document",
) -> list[list[float]] | None:
    """Embed a list of strings, batched up to Voyage's 128/call limit.

    Hits Voyage's REST API directly with httpx — we deliberately don't
    use the voyageai SDK because it pulls in tokenizers (Rust build) and
    doesn't deploy cleanly on Vercel's Python runtime.

    Returns None if Voyage isn't configured — callers should treat that
    as 'fall back to rule-based scoring' and not crash. Empty strings
    get substituted with a single space so the API doesn't reject them
    and the batch indices stay aligned with the caller.

    `input_type` should be 'document' when embedding job postings and
    'query' when embedding the candidate profile. Voyage uses different
    representations for retrieval vs. document.
    """
    if not settings.embeddings_enabled or not settings.voyage_api_key:
        # Off by default: scoring runs on the rule-based axes alone.
        logger.debug("Embeddings off (EMBEDDINGS_ENABLED / VOYAGE_API_KEY) — skipping")
        return None
    if not texts:
        return []

    # Voyage rejects empty strings — substitute a single space for any
    # empty input so the batch indices stay aligned with the caller.
    safe = [t if (t and t.strip()) else " " for t in texts]

    all_vectors: list[list[float]] = []
    headers = {
        "Authorization": f"Bearer {settings.voyage_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        for start in range(0, len(safe), MAX_BATCH):
            chunk = safe[start:start + MAX_BATCH]
            payload = {
                "input": chunk,
                "model": EMBEDDING_MODEL,
                "input_type": input_type,
            }
            try:
                r = await client.post(_VOYAGE_URL, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPStatusError as e:
                body = e.response.text[:300] if e.response is not None else ""
                logger.exception(
                    "Voyage embed HTTP %s for batch %d: %s",
                    e.response.status_code if e.response is not None else "?",
                    start, body,
                )
                raise RuntimeError(
                    f"Voyage embed failed: HTTP {e.response.status_code if e.response is not None else '?'}: {body}"
                ) from e
            except Exception as e:  # noqa: BLE001
                logger.exception("Voyage embed failed for batch %d", start)
                raise RuntimeError(f"Voyage embed failed: {type(e).__name__}: {e}") from e

            # Voyage response shape: { "data": [{"embedding": [...]}, ...], ... }
            for item in data.get("data", []):
                vec = item.get("embedding")
                if isinstance(vec, list):
                    all_vectors.append(vec)

    return all_vectors


async def embed_one(text: str, *, input_type: str = "document") -> list[float] | None:
    """Embed a single string. Returns None if Voyage is unconfigured."""
    vectors = await embed_texts([text], input_type=input_type)
    if vectors is None:
        return None
    return vectors[0] if vectors else None


def job_corpus(*, title: str, company: str, description: str | None,
               skills: Iterable[str] | None = None,
               requirements: Iterable[str] | None = None,
               keywords: Iterable[str] | None = None) -> str:
    """Build the text we embed per job. Stays small enough to stay cheap
    while including everything the scorer would want to compare against.
    Order matters slightly — Voyage weights earlier tokens a bit more,
    so title + company go first."""
    parts: list[str] = []
    if title:
        parts.append(f"Title: {title}")
    if company:
        parts.append(f"Company: {company}")
    if skills:
        parts.append("Skills: " + ", ".join(s for s in skills if s))
    if requirements:
        parts.append("Requirements: " + "; ".join(r for r in requirements if r))
    if keywords:
        parts.append("Keywords: " + ", ".join(k for k in keywords if k))
    if description:
        # Cap description so we don't overshoot the token budget on
        # particularly long postings — first ~2 k chars is plenty of signal.
        parts.append(f"\n{description[:2000]}")
    return "\n".join(parts).strip()


def profile_corpus(*, target_roles: Iterable[str] | None,
                   headline: str | None,
                   summary: str | None,
                   skills: Iterable[str] | None,
                   work_history: Iterable[dict] | None = None,
                   interests: Iterable[str] | None = None) -> str:
    """Build the text we embed per profile. Same shape as job_corpus
    so cosine similarity is meaningful — target_roles aligns to titles,
    headline to short company-blurb, summary to description, skills to
    skills, work history bullets to requirements."""
    parts: list[str] = []
    if target_roles:
        roles = [r for r in target_roles if r]
        if roles:
            parts.append("Target roles: " + ", ".join(roles))
    if interests:
        kw = [k for k in interests if k]
        if kw:
            parts.append("Interests: " + ", ".join(kw[:20]))
    if headline:
        parts.append(f"Headline: {headline}")
    if skills:
        sk = [s for s in skills if s]
        if sk:
            parts.append("Skills: " + ", ".join(sk[:30]))
    if work_history:
        recent_bullets: list[str] = []
        for entry in list(work_history)[:4]:
            title = entry.get("title") or ""
            company = entry.get("company") or ""
            line = f"{title} at {company}".strip()
            if line:
                recent_bullets.append(line)
            for b in (entry.get("bullets") or [])[:3]:
                if b:
                    recent_bullets.append(b)
        if recent_bullets:
            parts.append("Experience:\n- " + "\n- ".join(recent_bullets))
    if summary:
        parts.append(f"\n{summary[:1500]}")
    return "\n".join(parts).strip()


async def refresh_profile_embedding(db, profile) -> bool:
    """Re-embed a candidate profile after anything that feeds the corpus
    changes. Loads skills and work history itself; the caller commits.
    Returns False (and leaves the old vector) when Voyage is unconfigured
    or the call fails — scoring then uses rules only."""
    from sqlalchemy import select
    from app.models.candidate import CandidateSkill, CandidateWorkHistory

    if not hasattr(profile, "embedding"):
        return False
    skills = (await db.execute(
        select(CandidateSkill.skill_name).where(CandidateSkill.profile_id == profile.id)
    )).scalars().all()
    work = (await db.execute(
        select(CandidateWorkHistory)
        .where(CandidateWorkHistory.profile_id == profile.id)
        .order_by(CandidateWorkHistory.sort_order)
    )).scalars().all()
    text = profile_corpus(
        target_roles=profile.target_roles or [],
        headline=profile.headline,
        summary=profile.master_summary,
        skills=[s for s in skills if s],
        work_history=[
            {"title": w.title, "company": w.company, "bullets": w.bullets or []}
            for w in work
        ],
        interests=profile.search_keywords or [],
    )
    import asyncio
    try:
        # Bounded so a slow embedding service can't hold up a profile save.
        vector = await asyncio.wait_for(embed_one(text, input_type="query"), timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.warning("Profile embedding failed for profile %s: %s", profile.id, e)
        return False
    if vector is None:
        return False
    profile.embedding = vector
    return True


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two equal-dim vectors. Returns 0.0
    when either is empty or all-zero. Range: -1.0 to 1.0 in theory,
    but for embeddings in practice 0.4-0.9 covers most pairs.

    Accepts lists or numpy arrays (pgvector < 0.5 returns arrays, which
    raise on truthiness checks). Always returns a plain Python float:
    numpy scalars aren't JSON-serializable and this value ends up in
    JobScore.reasoning (JSONB)."""
    if a is None or b is None or len(a) == 0 or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        x = float(x)
        y = float(y)
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    import math
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
