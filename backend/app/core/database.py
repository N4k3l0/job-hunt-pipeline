from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import get_settings

settings = get_settings()


def engine_options(pool_size: int) -> dict:
    """Engine settings for Supabase's transaction pooler (port 6543).

    asyncpg's statement cache is always off: the pooler can run a client's
    next transaction on a different server connection.

    pool_size 0 (serverless, Vercel): a fresh connection per request, since
    each request may land on a new instance. Above 0 (long-running server,
    Railway): connections stay open between requests, and prepared
    statements get unique names so ones left on a shared server connection
    never clash.
    """
    if pool_size <= 0:
        return {
            "poolclass": NullPool,
            "echo": settings.sql_echo,
            "connect_args": {"statement_cache_size": 0},
        }
    return {
        "pool_size": pool_size,
        "max_overflow": pool_size,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "echo": settings.sql_echo,
        "connect_args": {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
        },
    }


engine = create_async_engine(settings.async_database_url, **engine_options(settings.db_pool_size))

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
    worker_engine = create_async_engine(settings.async_database_url, **engine_options(0))
    return async_sessionmaker(worker_engine, class_=AsyncSession, expire_on_commit=False)
