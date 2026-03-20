from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    environment: str = "development"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    # Database
    database_url: str = "postgresql+asyncpg://jobhunt:jobhunt_dev@localhost:5432/jobhunt"

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_anon_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # External APIs
    apify_api_token: str = ""
    apify_webhook_secret: str = ""
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    jsearch_rapidapi_key: str = ""
    firecrawl_api_key: str = ""
    anthropic_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
