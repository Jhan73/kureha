from pathlib import Path
from typing import AsyncIterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.pool import NullPool

from app.config import settings
from app.db import create_engine

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"


def _sync_url() -> str:
    # Alembic `command` + schema reset run sync (env.py calls asyncio.run).
    return settings.database_url.replace("+asyncpg", "+psycopg")


def _alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema() -> None:
    """Reset schema; upgrade -> downgrade -> upgrade once per session."""
    reset_engine = sa.create_engine(_sync_url())
    with reset_engine.connect() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
        # Schema drop removes extensions from init scripts; reinstall for tests.
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        conn.commit()
    reset_engine.dispose()

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
async def db_conn() -> AsyncIterator[AsyncConnection]:
    """Per-test transactional conn (own NullPool engine); roll back on teardown.

    Constraint-violation checks must use `async with db_conn.begin_nested():`.
    """
    test_engine = create_engine(poolclass=NullPool)
    try:
        async with test_engine.connect() as conn:
            trans = await conn.begin()
            try:
                yield conn
            finally:
                await trans.rollback()
    finally:
        await test_engine.dispose()


@pytest.fixture
async def tenant_id(db_conn: AsyncConnection) -> str:
    """Single fresh tenant; use `make_tenant()` when you need more control."""
    from tests.schema.helpers import make_tenant

    return await make_tenant(db_conn)


@pytest.fixture
async def rls_conn() -> AsyncIterator[AsyncConnection]:
    """Per-test conn as `app_runtime` (RLS enforced). Use for RLS assertions.

    Seed fixture rows via `db_conn` first; `app_runtime` cannot insert around
    denying policies.
    """
    test_engine = create_engine(settings.runtime_database_url, poolclass=NullPool)
    try:
        async with test_engine.connect() as conn:
            trans = await conn.begin()
            try:
                yield conn
            finally:
                await trans.rollback()
    finally:
        await test_engine.dispose()
