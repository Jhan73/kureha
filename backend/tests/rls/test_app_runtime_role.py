"""Guards the blocker flagged during PR 2's review (tasks.md task 2.9):
`app_user` is the Postgres bootstrap superuser and unconditionally bypasses
RLS. `app_runtime` (infra/postgres/init/02_app_runtime_role.sql) is the
restricted role RLS tests actually run through. This test proves that role
is genuinely restricted, so a future regression (e.g. `runtime_database_url`
silently repointed at `app_user`, or `app_runtime` granted BYPASSRLS) fails
loudly instead of producing a false-green RLS suite.
"""

import sqlalchemy as sa


async def test_app_runtime_is_not_superuser(db_conn) -> None:
    row = (
        await db_conn.execute(
            sa.text("SELECT rolsuper FROM pg_roles WHERE rolname = 'app_runtime'")
        )
    ).one()
    assert row.rolsuper is False


async def test_app_runtime_does_not_bypass_rls(db_conn) -> None:
    row = (
        await db_conn.execute(
            sa.text("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'app_runtime'")
        )
    ).one()
    assert row.rolbypassrls is False


async def test_app_user_bootstrap_role_is_superuser_and_bypasses_rls(db_conn) -> None:
    """Documents the actual risk this whole module exists to guard against:
    `app_user` (docker-compose.yml POSTGRES_USER) IS superuser + BYPASSRLS.
    If this ever flips to False, `rls_conn`'s docstring warning about
    `db_conn` being unsafe for RLS assertions goes stale and should be
    revisited."""
    row = (
        await db_conn.execute(
            sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'app_user'")
        )
    ).one()
    assert row.rolsuper is True
    assert row.rolbypassrls is True


async def test_rls_conn_fixture_connects_as_app_runtime(rls_conn) -> None:
    """Proves `rls_conn` (conftest.py) actually authenticates as the
    restricted role, not `app_user` -- the fixture's whole purpose."""
    current_user = (await rls_conn.execute(sa.text("SELECT current_user"))).scalar_one()
    assert current_user == "app_runtime"


async def test_runtime_engine_connects_as_non_superuser_non_bypassrls_role() -> None:
    """`app.db.runtime_engine` is what the composition root must import for
    request-scoped queries (see app/db.py's module docstring). This proves
    it actually resolves to the restricted role, not the `app_user`
    bootstrap superuser `app.db.engine` connects as -- a regression here
    would silently defeat every RLS policy in production."""
    from app.db import runtime_engine

    async with runtime_engine.connect() as conn:
        current_user = (await conn.execute(sa.text("SELECT current_user"))).scalar_one()
        assert current_user == "app_runtime"
        row = (
            await conn.execute(
                sa.text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        assert row.rolsuper is False
        assert row.rolbypassrls is False
