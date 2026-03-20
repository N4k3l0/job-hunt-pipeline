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

# Auto-discover tasks in worker modules
celery_app.autodiscover_tasks([
    "app.workers.discovery_tasks",
    "app.workers.parsing_tasks",
    "app.workers.scoring_tasks",
    "app.workers.tailoring_tasks",
    "app.workers.reminder_tasks",
])

# Celery Beat schedule — job discovery runs daily
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
    "check-follow-up-reminders": {
        "task": "app.workers.reminder_tasks.check_due_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
}
