"""Files in Supabase Storage.

The "resumes" bucket is private: files are read with the service key, and
shared with the user through short-lived signed links. Database rows store
the file's path in the bucket. Rows saved while the bucket was public hold a
public URL instead; `object_path` reads both.

The Supabase client is synchronous, so its network calls run in a thread
to keep the event loop free for other requests.
"""

import asyncio
import logging
from urllib.parse import unquote, urlparse

from supabase import create_client

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SIGNED_URL_SECONDS = 600
_PUBLIC_PREFIX = "/storage/v1/object/public/"


def _get_supabase():
    return create_client(settings.supabase_url, settings.supabase_service_key)


def object_path(bucket: str, stored: str) -> str:
    """The file's path in `bucket`, from a stored path or an old public URL."""
    if stored.startswith(("http://", "https://")):
        path = urlparse(stored).path
        prefix = f"{_PUBLIC_PREFIX}{bucket}/"
        if not path.startswith(prefix):
            raise ValueError(f"Not a file in the {bucket} bucket")
        return unquote(path[len(prefix):])
    return stored.lstrip("/")


async def upload_file(
    bucket: str,
    path: str,
    content: bytes,
    content_type: str,
) -> str:
    """Upload a file and return its path in the bucket."""
    def _upload():
        _get_supabase().storage.from_(bucket).upload(
            path=path,
            file=content,
            file_options={"content-type": content_type, "upsert": "true"},
        )

    await asyncio.to_thread(_upload)
    logger.info("Uploaded file to %s/%s", bucket, path)
    return path


async def download_file(bucket: str, path: str) -> bytes:
    """Download a file from Supabase Storage."""
    return await asyncio.to_thread(lambda: _get_supabase().storage.from_(bucket).download(path))


async def signed_url(bucket: str, path: str, expires_in: int = SIGNED_URL_SECONDS) -> str:
    """A link to the file that stops working after `expires_in` seconds."""
    result = await asyncio.to_thread(
        lambda: _get_supabase().storage.from_(bucket).create_signed_url(path, expires_in)
    )
    url = result.get("signedURL") or result.get("signedUrl")
    if not url:
        raise RuntimeError(f"Storage returned no signed link for {bucket}/{path}")
    return url


async def delete_file(bucket: str, path: str) -> None:
    await asyncio.to_thread(lambda: _get_supabase().storage.from_(bucket).remove([path]))
    logger.info("Deleted file %s/%s", bucket, path)
