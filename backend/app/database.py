from typing import Any
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings


def _engine_kwargs(url: str) -> dict[str, Any]:
    """
    Engine options that suit the driver in use.

    Connection pooling arguments are specific to server-backed databases;
    SQLite (used by the test suite) rejects them outright.
    """
    kwargs: dict[str, Any] = {"echo": settings.sql_echo}
    if url.startswith("sqlite"):
        return kwargs
    kwargs.update(pool_pre_ping=True, pool_size=10, max_overflow=20)
    return kwargs


engine = create_async_engine(settings.database_url, **_engine_kwargs(settings.database_url))

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
