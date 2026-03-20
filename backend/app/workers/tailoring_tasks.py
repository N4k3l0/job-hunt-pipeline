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
def generate_tailored_application(self, job_id: str, user_id: str):
    """Run the full tailoring pipeline for a job."""
    try:
        _run_async(_generate_async(job_id, user_id))
    except Exception as exc:
        logger.error("Tailoring failed for job %s: %s", job_id, exc)
        raise self.retry(exc=exc)


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


async def _generate_async(job_id: str, user_id: str):
    from app.services.tailoring.tailor_service import generate_tailored_application as tailor
    from sqlalchemy import select
    from app.models.job import Job

    async with create_worker_session()() as db:
        # Enrich description before tailoring
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            await _enrich_description_if_needed(db, job)
            await db.flush()

        application = await tailor(db, job_id, user_id)

        # Generate PDF
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

        await db.commit()
        logger.info("Tailoring complete for job %s, application %s", job_id, application.id)
