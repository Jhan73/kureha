"""Async SQLAlchemy Core engine wiring.

Kureha uses SQLAlchemy Core, not the ORM (design.md §1): RLS and
transaction-scoped `SET LOCAL` calls are expressed more directly in explicit
SQL than through an ORM's unit-of-work. This module owns the two
`AsyncEngine` singletons for the process, connected as two different
Postgres roles -- using the wrong one for the wrong purpose silently
defeats RLS, so the distinction is load-bearing, not stylistic:

- `engine` connects as `app_user` (`settings.database_url`), the Postgres
  bootstrap superuser. It is for Alembic (`migrations/env.py`) and any other
  schema-authority operation (DDL) that genuinely needs superuser
  privileges. It unconditionally BYPASSES RLS -- never import it to run a
  request-scoped business query.
- `runtime_engine` connects as `app_runtime` (`settings.runtime_database_url`),
  a restricted, non-superuser, NOBYPASSRLS role (design.md §4.2,
  `infra/postgres/init/02_app_runtime_role.sql`). This is what the FastAPI
  composition root (added in a later phase, tasks.md task 10.2) MUST import
  for every request-scoped query -- RLS policies are only meaningfully
  enforced against this role. See `tests/rls/test_app_runtime_role.py` for
  the assertion that guards this distinction from silently regressing.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings


def create_engine(url: str | None = None, **kwargs: Any) -> AsyncEngine:
    kwargs.setdefault("pool_pre_ping", True)
    return create_async_engine(url or settings.database_url, **kwargs)


engine: AsyncEngine = create_engine()
runtime_engine: AsyncEngine = create_engine(settings.runtime_database_url)
