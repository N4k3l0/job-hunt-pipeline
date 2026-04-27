import asyncio
import logging

from app.workers.celery_app import celery_app
from app.core.database import create_worker_session

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.workers.tailoring_tasks.generate_tailored_application",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def generate_tailored_application(self, job_id: str, user_id: str, tailored_id: str | None = None):
    """Run the full tailoring pipeline for a job. `tailored_id` is the placeholder
    row created by the API endpoint — the worker updates it in-place so the UI
    can poll a stable id."""
    try:
        _run_async(_generate_async(job_id, user_id, tailored_id))
    except Exception as exc:
        logger.error("Tailoring failed for job %s: %s", job_id, exc)
        if tailored_id:
            try:
                _run_async(_mark_failed(tailored_id, str(exc)))
            except Exception as inner:
                logger.error("Could not record failure for %s: %s", tailored_id, inner)
        raise self.retry(exc=exc)


async def _mark_failed(tailored_id: str, message: str):
    from sqlalchemy import select
    from app.models.tailoring import TailoredApplication

    async with create_worker_session()() as db:
        result = await db.execute(
            select(TailoredApplication).where(TailoredApplication.id == tailored_id)
        )
        app = result.scalar_one_or_none()
        if app:
            app.approval_status = "failed"
            app.progress_step = message[:500]
            await db.commit()


async def _enrich_description_if_needed(db, job):
    """Fetch full job description via Firecrawl if current one is too short."""
    desc = job.raw_description or ""
    if len(desc) > 500 or not job.job_url:
        return  # Already have enough content or no URL to scrape

    logger.info("Description too short (%d chars), fetching full page for job %s", len(desc), job.id)
    try:
        from app.services.discovery.firecrawl_service import scrape_url
        full_content = await scrape_url(job.job_url)
        if full_content and len(full_content) > len(desc):
            job.raw_description = full_content
            logger.info("Enriched description: %d -> %d chars", len(desc), len(full_content))
    except Exception as e:
        logger.warning("Failed to fetch full description for job %s: %s", job.id, e)


async def _generate_async(job_id: str, user_id: str, tailored_id: str | None):
    from app.services.tailoring.tailor_service import generate_tailored_application as tailor
    from sqlalchemy import select
    from app.models.job import Job
    from app.models.tailoring import TailoredApplication

    async with create_worker_session()() as db:
        async def report(step: str):
            if not tailored_id:
                return
            res = await db.execute(
                select(TailoredApplication).where(TailoredApplication.id == tailored_id)
            )
            row = res.scalar_one_or_none()
            if row:
                row.progress_step = step
                await db.commit()

        await report("Fetching job description")
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            await _enrich_description_if_needed(db, job)
            await db.flush()

        application = await tailor(
            db, job_id, user_id,
            tailored_id=tailored_id,
            progress_callback=report,
        )

        await report("Generating PDF")
        try:
            from app.services.pdf.generator import generate_resume_pdf
            pdf_url = await generate_resume_pdf(
                tailored_data=application.tailored_resume_json,
                user_id=user_id,
                application_id=str(application.id),
            )
            application.tailored_resume_url = pdf_url
        except Exception as e:
            logger.warning("PDF generation failed, continuing without PDF: %s", e)

        application.progress_step = None
        await db.commit()
        logger.info("Tailoring complete for job %s, application %s", job_id, application.id)
