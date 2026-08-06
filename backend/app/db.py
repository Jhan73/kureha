from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings


def create_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    kwargs.setdefault("pool_pre_ping", True)
    return create_async_engine(url or settings.database_url, **kwargs)


engine: AsyncEngine = create_engine()
runtime_engine: AsyncEngine = create_engine(settings.runtime_database_url)
