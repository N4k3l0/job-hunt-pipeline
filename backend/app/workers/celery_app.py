"""Celery setup — gated behind USE_CELERY env so production cold-starts
don't pay the celery+kombu+redis import cost (~1-2s on Vercel Python
runtime). Production uses Vercel Cron for discovery and synchronous
in-request execution for everything else; Celery is only useful for
local development, where you set USE_CELERY=true to spin up a worker.

When the gate is off, celery_app is a no-op stub: @celery_app.task()
returns the underlying function unchanged so the existing
`@celery_app.task(...)` decorations elsewhere in the codebase remain
valid imports without doing anything at runtime.
"""

import os

_USE_CELERY = os.environ.get("USE_CELERY", "false").lower() in ("1", "true", "yes")


if _USE_CELERY:
    from celery import Celery
    from celery.schedules import crontab

    from app.core.config import get_settings

    settings = get_settings()

    celery_app = Celery(
        "job_hunt_pipeline",
        broker=settings.redis_url,
        backend=settings.redis_url,
    )

    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        result_expires=3600,
    )

    celery_app.autodiscover_tasks([
        "app.workers.discovery_tasks",
        "app.workers.parsing_tasks",
        "app.workers.scoring_tasks",
        "app.workers.tailoring_tasks",
        "app.workers.reminder_tasks",
    ])

    celery_app.conf.beat_schedule = {
        "discover-adzuna-daily": {
            "task": "app.workers.discovery_tasks.run_adzuna_discovery",
            "schedule": crontab(hour=6, minute=0),
        },
        "discover-remoteok-daily": {
            "task": "app.workers.discovery_tasks.run_remoteok_discovery",
            "schedule": crontab(hour=6, minute=15),
        },
        "discover-arbeitnow-daily": {
            "task": "app.workers.discovery_tasks.run_arbeitnow_discovery",
            "schedule": crontab(hour=6, minute=30),
        },
        "discover-jsearch-every-3-days": {
            "task": "app.workers.discovery_tasks.run_jsearch_discovery",
            "schedule": crontab(hour=7, minute=0, day_of_week="mon,thu"),
        },
        "discover-himalayas-twice-daily": {
            "task": "app.workers.discovery_tasks.run_himalayas_discovery",
            "schedule": crontab(hour="6,18", minute=45),
        },
        "discover-remotive-daily": {
            "task": "app.workers.discovery_tasks.run_remotive_discovery",
            "schedule": crontab(hour=7, minute=15),
        },
        "discover-weworkremotely-daily": {
            "task": "app.workers.discovery_tasks.run_weworkremotely_discovery",
            "schedule": crontab(hour=7, minute=30),
        },
        "discover-crossover-daily": {
            "task": "app.workers.discovery_tasks.run_crossover_discovery",
            "schedule": crontab(hour=7, minute=45),
        },
        "check-follow-up-reminders": {
            "task": "app.workers.reminder_tasks.check_due_reminders",
            "schedule": crontab(hour=8, minute=0),
        },
    }
else:
    # No-op stub. Keeps the existing @celery_app.task(...) decorators
    # valid (they return the function unchanged) while skipping the
    # heavy celery + kombu + redis imports entirely.
    class _NoOpCelery:
        def task(self, *args, **kwargs):
            def decorator(fn):
                return fn
            # Support both @celery_app.task and @celery_app.task(name=...)
            if args and callable(args[0]) and not kwargs:
                return args[0]
            return decorator

    celery_app = _NoOpCelery()
