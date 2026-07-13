"""Shared fixtures for backend tests.

Applies every Alembic migration against the local Postgres (started via
`docker compose up -d postgres`, see docker-compose.yml at the repo root)
once per test session, and proves upgrade()/downgrade() round-trip cleanly
(backend/AGENTS.md: "Every migration must be reversible") before handing out
a per-test transactional connection.
"""

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
    # Resetting the schema and driving Alembic's `command` API must happen
    # outside any running asyncio event loop (migrations/env.py owns its own
    # async engine and calls asyncio.run() internally) -> use a sync driver.
    return settings.database_url.replace("+asyncpg", "+psycopg")


def _alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema() -> None:
    """Reset `public` and apply all migrations once per test run.

    Also exercises upgrade -> downgrade -> upgrade so a broken `downgrade()`
    fails the whole test session instead of silently rotting.
    """
    reset_engine = sa.create_engine(_sync_url())
    with reset_engine.connect() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
        # Recreating the schema drops any extension objects that lived in it
        # (btree_gist/pgcrypto, normally installed once by
        # infra/postgres/init/01_extensions.sql at container init time, not
        # by a migration -- see that file's own comment on why). Re-create
        # them here so a schema reset between test runs doesn't lose them;
        # this is test-harness bookkeeping only, not part of the migration
        # path itself.
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
    """One transactional connection per test, rolled back on teardown.

    Uses its own engine (NullPool, no cross-test pooling) rather than the
    shared `app.db.engine` singleton: pytest-asyncio gives each test
    function its own event loop by default, and an asyncio connection pool
    created against one loop cannot be reused from another (surfaces as
    unrelated-looking `AttributeError`/`RuntimeError` from asyncio's
    proactor internals on the second test, not a clean error) -- see
    apply-progress notes for kureha-mvp PR 2.

    Tests that need to assert a constraint violation (UNIQUE, CHECK,
    EXCLUDE, or a trigger raising) must wrap the failing statement in
    `async with db_conn.begin_nested():` so the outer transaction used for
    isolation survives the error.
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
    """A fresh tenant for tests that only need one. Tests needing two (or
    more) tenants, or a non-default name, call `make_tenant()` directly."""
    from tests.schema.helpers import make_tenant

    return await make_tenant(db_conn)
