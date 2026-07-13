"""Async SQLAlchemy Core engine wiring.

Kureha uses SQLAlchemy Core, not the ORM (design.md §1): RLS and
transaction-scoped `SET LOCAL` calls are expressed more directly in explicit
SQL than through an ORM's unit-of-work. This module owns the single
`AsyncEngine` for the process; both Alembic (`migrations/env.py`) and the
FastAPI app (composition root, added in a later phase) import it so there is
exactly one place that knows the connection string.
"""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings


def create_engine() -> AsyncEngine:
    return create_async_engine(settings.database_url, pool_pre_ping=True)


engine: AsyncEngine = create_engine()
