import logging

from supabase import create_client

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _get_supabase():
    return create_client(settings.supabase_url, settings.supabase_service_key)


async def upload_file(
    bucket: str,
    path: str,
    content: bytes,
    content_type: str,
) -> str:
    """Upload a file to Supabase Storage and return the public URL."""
    supabase = _get_supabase()

    # Upload file
    supabase.storage.from_(bucket).upload(
        path=path,
        file=content,
        file_options={"content-type": content_type, "upsert": "true"},
    )

    # Get public URL
    url = supabase.storage.from_(bucket).get_public_url(path)
    logger.info("Uploaded file to %s/%s", bucket, path)
    return url


async def download_file(bucket: str, path: str) -> bytes:
    """Download a file from Supabase Storage."""
    supabase = _get_supabase()
    response = supabase.storage.from_(bucket).download(path)
    return response
