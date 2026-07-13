"""Task 2.11: rate_counters cleanup job (design.md §4.4).

design.md's own MVP plan: "pg_cron ejecutado cada hora ... si pg_cron no
esta disponible, una Lambda CloudWatch-scheduled cada hora hace el mismo
DELETE". Vanilla `postgres:16` (docker-compose.yml's local image) does NOT
ship `pg_cron` (it needs a build with the extension compiled in, e.g. a
citusdata image, or an RDS parameter-group change on AWS) -- `CREATE
EXTENSION pg_cron` would hard-fail locally if attempted unconditionally, so
this migration guards on `pg_available_extensions` before doing anything
pg_cron-specific, exactly as `01_extensions.sql`/776b456050fe already guard
on role/extension existence for portability. These tests confirm: (1) the
migration is a safe no-op locally (no pg_cron -> no scheduled job, no
error), and (2) IF pg_cron were available, the schedule would be registered
correctly (skipped, not failed, when unavailable -- see `pytest.skip` below).
The actual cleanup DELETE query's correctness is already covered by
`test_sessions_and_rate_limiting.py::test_rate_counter_cleanup_deletes_only_rows_older_than_24h`.
"""

import sqlalchemy as sa
import pytest


async def _pg_cron_available(conn) -> bool:
    result = await conn.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron'")
    )
    return result.first() is not None


async def test_migration_is_a_safe_noop_without_pg_cron(db_conn) -> None:
    """The full migration suite (conftest.py's session-scoped upgrade ->
    downgrade -> upgrade cycle) already proves this migration doesn't raise
    locally -- this test makes the assumption explicit: pg_cron is NOT
    available in the local/CI Postgres image, so the guarded branch must
    never have run."""
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
