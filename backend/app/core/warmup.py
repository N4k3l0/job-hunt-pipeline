"""Get the backend ready before it takes its first request.

After a deploy, the first page load waited about 27 seconds for every
request while the new container loaded code the first time it was used,
opened its database connections and fetched the login keys. Uvicorn opens
the port only after startup, and Railway switches traffic only once the
health check answers, so doing that work here means nobody meets a cold
backend. Every step is timed and can fail without stopping the start.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import pkgutil
import time

logger = logging.getLogger(__name__)

STEP_TIMEOUT_SECONDS = 20.0


def _load_all_modules() -> int:
    """Import every module now, not on the first request that needs it
    (many are imported inside the functions that use them)."""
    import app

    loaded = 0
    for info in pkgutil.walk_packages(app.__path__, "app."):
        try:
            importlib.import_module(info.name)
            loaded += 1
        except Exception as e:  # noqa: BLE001 — one module mustn't stop the start
            logger.warning("Warm-up: couldn't load %s: %s", info.name, e)
    return loaded


async def _open_database_connections(count: int) -> int:
    """Open the pool's connections at once, so none is opened mid-request."""
    from sqlalchemy import text

    from app.core.database import engine

    async def one() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            await asyncio.sleep(0.2)  # held together, so each one is a separate connection

    await asyncio.gather(*(one() for _ in range(count)))
    return count


def _fetch_login_keys() -> int:
    from app.core.auth import _get_jwks_client
    from app.core.config import get_settings

    if not get_settings().supabase_url:
        return 0
    return len(_get_jwks_client().get_signing_keys())


def _draw_a_pdf() -> int:
    from app.services.auto_apply.resume_pdf import build_resume_pdf

    return len(build_resume_pdf({"name": "Warm up", "summary": "Getting ready.", "experience": [], "skills": []}))


def _create_ai_client() -> str:
    from app.llm.client import llm_client

    llm_client._client_lazy()
    return "ready"


async def warm_up() -> dict[str, str]:
    """Run each step, returning what happened to each."""
    from app.core.config import get_settings

    settings = get_settings()
    outcome: dict[str, str] = {}
    started = time.monotonic()

    async def step(name: str, work) -> None:
        begun = time.monotonic()
        try:
            result = await asyncio.wait_for(work(), timeout=STEP_TIMEOUT_SECONDS)
            outcome[name] = f"{result} in {time.monotonic() - begun:.1f}s"
        except Exception as e:  # noqa: BLE001 — the backend starts anyway
            outcome[name] = f"failed after {time.monotonic() - begun:.1f}s: {type(e).__name__}"
            logger.warning("Warm-up step %s failed: %s", name, e)

    await step("modules", lambda: asyncio.to_thread(_load_all_modules))
    if settings.db_pool_size > 0:
        await step("database", lambda: _open_database_connections(settings.db_pool_size))
    await step("login keys", lambda: asyncio.to_thread(_fetch_login_keys))
    await step("pdf", lambda: asyncio.to_thread(_draw_a_pdf))
    await step("ai client", lambda: asyncio.to_thread(_create_ai_client))
    logger.info("Warmed up in %.1fs: %s", time.monotonic() - started,
                "; ".join(f"{k} {v}" for k, v in outcome.items()))
    return outcome
