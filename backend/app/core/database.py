import logging
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

logger.info(f"DB environment={settings.environment}, is_production={settings.is_production}")
logger.info(f"DB URL host: {settings.async_database_url.split('@')[-1] if '@' in settings.async_database_url else 'no-host'}")

# Always use NullPool and disable prepared statements for Supabase/PgBouncer
engine = create_async_engine(
    settings.async_database_url,
    poolclass=NullPool,
    echo=not settings.is_production,
    connect_args={"statement_cache_size": 0},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


def create_worker_session():
    """Create a fresh async session factory for Celery workers.

    Each Celery task runs in a forked process with its own event loop,
    so it needs its own engine to avoid loop conflicts.
    """
    worker_engine = create_async_engine(
        settings.async_database_url,
        poolclass=NullPool,
        echo=not settings.is_production,
        connect_args={"statement_cache_size": 0},
    )
    return async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)
