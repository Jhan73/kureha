import sqlalchemy as sa
import pytest


async def _pg_cron_available(conn) -> bool:
    result = await conn.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron'")
    )
    return result.first() is not None


async def test_migration_is_a_safe_noop_without_pg_cron(db_conn) -> None:
    if await _pg_cron_available(db_conn):
        pytest.skip("pg_cron is available in this environment -- see the other test instead")

    result = await db_conn.execute(
        sa.text("SELECT 1 FROM pg_extension WHERE extname = 'pg_cron'")
    )
    assert result.first() is None


async def test_pg_cron_job_registered_when_extension_available(db_conn) -> None:
    if not await _pg_cron_available(db_conn):
        pytest.skip("pg_cron is not available in this Postgres image -- expected locally")

    row = (
        await db_conn.execute(
            sa.text("SELECT jobname, schedule FROM cron.job WHERE jobname = 'rate_counters_cleanup'")
        )
    ).one()
    assert row.jobname == "rate_counters_cleanup"
