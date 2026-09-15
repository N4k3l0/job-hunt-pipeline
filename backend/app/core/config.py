from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Database
    database_url: str = "postgresql+asyncpg://jobhunt:jobhunt_dev@localhost:5432/jobhunt"
    # Connections each server process keeps open. 0 opens a fresh one per
    # request (Vercel); set it where the server keeps running (Railway).
    db_pool_size: int = 0
    # Log every SQL statement. Local debugging only: slow with big batches.
    sql_echo: bool = False

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_anon_key: str = ""

    # External APIs
    jsearch_rapidapi_key: str = ""
    firecrawl_api_key: str = ""
    anthropic_api_key: str = ""

    # Frontend URL — used to build the magic-link redirect_to in the invite
    # flow. Falls back to the first cors_origin if unset.
    frontend_url: str = ""
    # Public address of this backend, for links in emails (unsubscribe).
    # On Railway, RAILWAY_PUBLIC_DOMAIN fills it in when this is unset.
    api_public_url: str = ""

    # Email (services/notifications/email.py). Railway's plan blocks SMTP,
    # so email goes out through an HTTPS service:
    #   resend       RESEND_API_KEY and EMAIL_FROM on a domain verified with Resend
    #   apps_script  EMAIL_RELAY_URL and EMAIL_RELAY_SECRET: a Google Apps Script
    #                web app in the sending Gmail account (scripts/email_relay.gs)
    # Unset: nothing is sent.
    email_provider: str = ""
    resend_api_key: str = ""
    email_from: str = ""
    email_relay_url: str = ""
    email_relay_secret: str = ""
    # The daily email goes out on the first scheduler run at or after this hour (UTC).
    digest_hour_utc: int = 7

    @property
    def async_database_url(self) -> str:
        """Convert standard postgresql:// URL to asyncpg format."""
        url = self.database_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    # Unknown entries (settings a newer version removed) are ignored rather
    # than stopping the app from starting.
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
