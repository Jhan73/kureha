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
    row = (
        await db_conn.execute(
            sa.text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'app_user'")
        )
    ).one()
    assert row.rolsuper is True
    assert row.rolbypassrls is True


async def test_rls_conn_fixture_connects_as_app_runtime(rls_conn) -> None:
    current_user = (await rls_conn.execute(sa.text("SELECT current_user"))).scalar_one()
    assert current_user == "app_runtime"


async def test_runtime_engine_connects_as_non_superuser_non_bypassrls_role() -> None:
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
