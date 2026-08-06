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
