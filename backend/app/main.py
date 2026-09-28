import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.llm.client import LLMCreditsExhausted
from app.api.v1 import (
    auth, candidates, jobs, tailoring, tracking, analytics, cron, feedback,
    invite_requests, auto_apply, ratings, job_alerts, notifications,
)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Ready before the first request: Uvicorn opens the port only after
    # this, and Railway waits for /health (app/core/warmup.py). Not on
    # Vercel, where every cold start would pay for it.
    if settings.environment != "test" and not os.environ.get("VERCEL"):
        from app.core.warmup import warm_up
        await warm_up()
    yield


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(
        lifespan=_lifespan,
        title="Job Hunt Pipeline",
        description="Automated job discovery, scoring, and application tailoring",
        version="0.1.0",
    )

    # Added before CORS, so CORS wraps it: a crash still comes back with
    # CORS headers the browser can read. Without them the page only saw
    # "Failed to fetch" and couldn't say what went wrong.
    @app.middleware("http")
    async def readable_errors(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled error on %s %s", request.method, request.url.path)
            return JSONResponse(status_code=500, content={
                "detail": "Something went wrong on our side. Please try again, and tell us if it keeps happening.",
            })

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(LLMCreditsExhausted)
    async def ai_paused(request: Request, exc: LLMCreditsExhausted):
        # A plain "try again later" rather than a 500 while the credits are out.
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # API routes
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(candidates.router, prefix="/api/v1/candidates", tags=["candidates"])
    app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
    app.include_router(tailoring.router, prefix="/api/v1/tailoring", tags=["tailoring"])
    app.include_router(tracking.router, prefix="/api/v1/tracking", tags=["tracking"])
    app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
    app.include_router(cron.router, prefix="/api/v1/cron", tags=["cron"])
    app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"])
    app.include_router(invite_requests.router, prefix="/api/v1/invite-requests", tags=["invite-requests"])
    app.include_router(auto_apply.router, prefix="/api/v1/auto-apply", tags=["auto-apply"])
    app.include_router(ratings.router, prefix="/api/v1/ratings", tags=["ratings"])
    app.include_router(job_alerts.router, prefix="/api/v1/job-alerts", tags=["job-alerts"])
    app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["notifications"])

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": "0.1.0"}

    @app.get("/health/db")
    async def db_health():
        try:
            from sqlalchemy import text
            from app.core.database import engine
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return {"status": "connected"}
        except Exception as e:
            return {"status": "error", "error": str(e), "type": type(e).__name__}

    return app


app = create_app()
