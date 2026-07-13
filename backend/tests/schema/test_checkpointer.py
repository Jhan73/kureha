"""Task 2.10: LangGraph checkpointer tables (design.md §4.4).

`AsyncPostgresSaver`/`PostgresSaver` (langgraph-checkpoint-postgres) own
their own DDL via `.setup()` (see `MIGRATIONS` in
`langgraph.checkpoint.postgres.base`) -- this migration invokes the sync
`PostgresSaver.setup()` directly (see migration docstring for why: calling
the async variant from inside an already-running Alembic async migration
would nest event loops). These tests only confirm the tables the migration
is responsible for actually exist and are usable; they are not a test of
LangGraph's own checkpointing logic.
"""

import sqlalchemy as sa

EXPECTED_TABLES = {"checkpoints", "checkpoint_writes", "checkpoint_blobs", "checkpoint_migrations"}


async def test_checkpointer_tables_exist(db_conn) -> None:
    result = await db_conn.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = ANY(:names)"
        ),
        {"names": list(EXPECTED_TABLES)},
    )
    found = {row.table_name for row in result}
    assert found == EXPECTED_TABLES


async def test_checkpoints_thread_id_is_the_tenant_prefixed_key(db_conn) -> None:
    """design.md §8.6: `thread_id` format is `"{tenant_id}:{user_id}:{random}"`
    -- confirms `split_part(thread_id, ':', 1)` (used by the RLS policy,
    tests/rls/test_checkpointer_rls.py) actually extracts the tenant_id."""
    thread_id = "11111111-1111-1111-1111-111111111111:user-1:abc123"
    await db_conn.execute(
        sa.text(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint) "
            "VALUES (:thread_id, '', 'chk-1', '{}'::jsonb)"
        ),
        {"thread_id": thread_id},
    )
    row = (
        await db_conn.execute(
            sa.text("SELECT split_part(thread_id, ':', 1) AS tenant_id FROM checkpoints WHERE thread_id = :t"),
            {"t": thread_id},
        )
    ).one()
    assert row.tenant_id == "11111111-1111-1111-1111-111111111111"
