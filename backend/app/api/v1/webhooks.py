import hashlib
import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


@router.post("/apify")
async def apify_webhook(request: Request):
    """Handle Apify actor run completion webhook.

    Apify sends a POST when an actor run succeeds.
    We verify the HMAC signature, extract the run ID,
    and queue a Celery task to fetch and process the results.
    """
    # Verify webhook signature
    body = await request.body()
    signature = request.headers.get("x-apify-webhook-signature", "")

    if settings.apify_webhook_secret:
        expected = hmac.new(
            settings.apify_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature",
            )

    payload = await request.json()
    actor_run_id = payload.get("resource", {}).get("id")
    event_type = payload.get("eventType")

    if event_type != "ACTOR.RUN.SUCCEEDED":
        return {"status": "ignored", "event_type": event_type}

    if not actor_run_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing actor run ID",
        )

    # Determine actor type from the payload
    actor_id = payload.get("resource", {}).get("actId", "")
    actor_type = "linkedin"  # default
    actor_id_lower = actor_id.lower() if actor_id else ""
    if "indeed" in actor_id_lower:
        actor_type = "indeed"
    elif "google" in actor_id_lower:
        actor_type = "google"

    # Run inline. Production has no Celery worker, so .delay() was a
    # silent no-op — Apify webhook deliveries were getting ack'd but
    # the actor results never ingested.
    from app.workers.discovery_tasks import _process_apify_async
    try:
        await _process_apify_async(actor_run_id, actor_type)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception(
            "Apify webhook processing failed for run %s", actor_run_id
        )
        raise HTTPException(
            status_code=502,
            detail=f"Apify processing failed: {type(e).__name__}: {e}",
        )

    return {"status": "processed", "actor_run_id": actor_run_id, "actor_type": actor_type}
