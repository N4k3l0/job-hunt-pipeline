"""Send one email through the configured HTTPS email service.

Railway's plan blocks outbound SMTP, so both providers are HTTPS APIs:
- resend: Resend's API, from an address on a domain verified with Resend.
- apps_script: a Google Apps Script web app deployed in the sending Gmail
  account (scripts/email_relay.gs). It sends with that account's Gmail,
  so no domain is needed; consumer Gmail allows 100 recipients a day.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)


class EmailNotConfigured(RuntimeError):
    pass


class EmailFailed(RuntimeError):
    pass


def email_configured() -> bool:
    settings = get_settings()
    if settings.email_provider == "resend":
        return bool(settings.resend_api_key and settings.email_from)
    if settings.email_provider == "apps_script":
        return bool(settings.email_relay_url and settings.email_relay_secret)
    return False


def api_public_url() -> str:
    settings = get_settings()
    if settings.api_public_url:
        return settings.api_public_url.rstrip("/")
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    return f"https://{domain}" if domain else ""


def frontend_url() -> str:
    settings = get_settings()
    return (settings.frontend_url or (settings.cors_origin_list[0] if settings.cors_origin_list else "")).rstrip("/")


async def send_email(*, to: str, subject: str, html: str, text: str, unsubscribe_url: str | None = None) -> None:
    """Raises EmailNotConfigured or EmailFailed."""
    settings = get_settings()
    if not email_configured():
        raise EmailNotConfigured("Email sending isn't set up")

    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        try:
            if settings.email_provider == "resend":
                payload = {"from": settings.email_from, "to": [to], "subject": subject, "html": html, "text": text}
                if unsubscribe_url:
                    payload["headers"] = {"List-Unsubscribe": f"<{unsubscribe_url}>"}
                r = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json=payload,
                )
                if r.status_code >= 300:
                    raise EmailFailed(f"Resend answered {r.status_code}: {r.text[:200]}")
                return

            # Apps Script web apps answer a POST with a redirect to the
            # result, which httpx follows with a GET.
            r = await client.post(settings.email_relay_url, json={
                "secret": settings.email_relay_secret, "to": to, "subject": subject, "html": html, "text": text,
            })
            try:
                body = r.json()
            except ValueError:
                body = {}
            if r.status_code >= 300 or not body.get("ok"):
                raise EmailFailed(f"Email relay answered {r.status_code}: {body.get('error') or r.text[:200]}")
        except httpx.HTTPError as e:
            raise EmailFailed(f"Couldn't reach the email service: {type(e).__name__}") from e
