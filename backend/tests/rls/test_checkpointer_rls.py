"""Task 2.10: RLS isolation for checkpoints/checkpoint_writes/checkpoint_blobs
(migration 043b5dd9768e), keyed by `split_part(thread_id, ':', 1)` -- design.md
§4.4/§8.6. `app_runtime` must only see checkpoint rows whose `thread_id`
tenant prefix matches `app.tenant_id`, even though the raw `thread_id` string
of another tenant's thread is technically knowable/guessable.
"""

import sqlalchemy as sa

from tests.rls.helpers import set_app_context

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


async def test_checkpoints_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    thread_id = f"{TENANT_B}:user-1:abc"
    await set_app_context(rls_conn, tenant_id=TENANT_B, role="patient")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint) "
            "VALUES (:t, '', 'chk-1', '{}'::jsonb)"
        ),
        {"t": thread_id},
    )

    await set_app_context(rls_conn, tenant_id=TENANT_A, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT thread_id FROM checkpoints"))).all()
    assert rows == []


async def test_checkpoints_same_tenant_select_returns_the_row(rls_conn) -> None:
    thread_id = f"{TENANT_A}:user-1:abc"
    await set_app_context(rls_conn, tenant_id=TENANT_A, role="patient")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint) "
            "VALUES (:t, '', 'chk-1', '{}'::jsonb)"
        ),
        {"t": thread_id},
    )

    rows = (await rls_conn.execute(sa.text("SELECT thread_id FROM checkpoints"))).all()
    assert [row.thread_id for row in rows] == [thread_id]


async def test_checkpoint_writes_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    thread_id = f"{TENANT_B}:user-1:abc"
    await set_app_context(rls_conn, tenant_id=TENANT_B, role="patient")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO checkpoint_writes "
            "(thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, blob) "
            "VALUES (:t, '', 'chk-1', 'task-1', 0, 'messages', :blob)"
        ),
        {"t": thread_id, "blob": b"payload"},
    )

    await set_app_context(rls_conn, tenant_id=TENANT_A, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT thread_id FROM checkpoint_writes"))).all()
    assert rows == []


async def test_checkpoint_blobs_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    thread_id = f"{TENANT_B}:user-1:abc"
    await set_app_context(rls_conn, tenant_id=TENANT_B, role="patient")
    await rls_conn.execute(
        sa.text(
            "INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type, blob) "
            "VALUES (:t, '', 'messages', '1', 'json', :blob)"
        ),
        {"t": thread_id, "blob": b"payload"},
    )

    await set_app_context(rls_conn, tenant_id=TENANT_A, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT thread_id FROM checkpoint_blobs"))).all()
    assert rows == []
