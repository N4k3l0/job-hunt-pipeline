from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.v1 import auth, candidates, jobs, scoring, tailoring, tracking, analytics, webhooks

settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Job Hunt Pipeline",
        description="Automated job discovery, scoring, and application tailoring",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(candidates.router, prefix="/api/v1/candidates", tags=["candidates"])
    app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["jobs"])
    app.include_router(scoring.router, prefix="/api/v1/scoring", tags=["scoring"])
    app.include_router(tailoring.router, prefix="/api/v1/tailoring", tags=["tailoring"])
    app.include_router(tracking.router, prefix="/api/v1/tracking", tags=["tracking"])
    app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])
    app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])

    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": "0.1.0"}

    @app.post("/trigger-discovery")
    async def trigger_discovery():
        from app.workers.discovery_tasks import (
            run_adzuna_discovery, run_remoteok_discovery,
            run_arbeitnow_discovery,
        )
        run_adzuna_discovery.delay()
        run_remoteok_discovery.delay()
        run_arbeitnow_discovery.delay()
        return {"status": "queued", "sources": ["adzuna", "remoteok", "arbeitnow"]}

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
