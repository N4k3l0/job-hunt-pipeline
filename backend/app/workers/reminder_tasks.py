from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.reminder_tasks.check_due_reminders")
def check_due_reminders():
    """Check for follow-up reminders that are due today."""
    # TODO: Implement
    # 1. Query application_tracking for follow_up_date <= today
    # 2. Create notification/email for each
    pass
