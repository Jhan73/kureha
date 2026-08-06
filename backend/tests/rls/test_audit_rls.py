import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from tests.rls.helpers import seed_tenant, set_app_context
from tests.schema.helpers import expect_violation

NIL_UUID = "00000000-0000-0000-0000-000000000000"


async def _insert_audit_row(conn, tenant_id, actor_id, *, action="appointment.create"):
    return await conn.execute(
        sa.text(
            "INSERT INTO audit_logs (tenant_id, actor_id, actor_type, action, object_type) "
            "VALUES (:t, :actor, 'user', :action, 'appointment') RETURNING id"
        ),
        {"t": tenant_id, "actor": actor_id, "action": action},
    )


async def test_audit_logs_insert_with_returning_allowed_for_non_admin_actor(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    actor_id = "11111111-1111-1111-1111-111111111111"

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception", user_id=actor_id)
    result = await _insert_audit_row(rls_conn, tenant_id, actor_id)
    assert result.scalar_one() is not None


async def test_audit_logs_system_actor_insert_with_returning_allowed_for_non_admin(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    result = await rls_conn.execute(
        sa.text(
            "INSERT INTO audit_logs (tenant_id, actor_id, actor_type, action, object_type) "
            "VALUES (:t, NULL, 'system', 'rate_counter.cleanup', 'rate_counters') RETURNING id"
        ),
        {"t": tenant_id},
    )
    assert result.scalar_one() is not None


async def test_audit_logs_insert_cross_tenant_rejected(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    actor_id = "11111111-1111-1111-1111-111111111111"

    await set_app_context(rls_conn, tenant_id=tenant_a, role="reception", user_id=actor_id)
    async with expect_violation(rls_conn, DBAPIError, match="row-level security"):
        await rls_conn.execute(
            sa.text(
                "INSERT INTO audit_logs (tenant_id, actor_id, actor_type, action, object_type) "
                "VALUES (:t, :actor, 'user', 'appointment.create', 'appointment')"
            ),
            {"t": tenant_b, "actor": actor_id},
        )


async def test_audit_logs_admin_sees_every_actors_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    actor_id = "11111111-1111-1111-1111-111111111111"

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception", user_id=actor_id)
    row_id = (await _insert_audit_row(rls_conn, tenant_id, actor_id)).scalar_one()

    await set_app_context(rls_conn, tenant_id=tenant_id, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM audit_logs"))).all()
    assert [str(row.id) for row in rows] == [str(row_id)]


async def test_audit_logs_actor_sees_only_their_own_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    actor_a = "11111111-1111-1111-1111-111111111111"
    actor_b = "22222222-2222-2222-2222-222222222222"

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception", user_id=actor_a)
    row_a = (await _insert_audit_row(rls_conn, tenant_id, actor_a)).scalar_one()

    await set_app_context(rls_conn, tenant_id=tenant_id, role="professional", user_id=actor_b)
    await _insert_audit_row(rls_conn, tenant_id, actor_b)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception", user_id=actor_a)
    rows = (await rls_conn.execute(sa.text("SELECT id FROM audit_logs"))).all()
    assert [str(row.id) for row in rows] == [str(row_a)]


async def test_audit_logs_non_admin_non_actor_select_returns_zero_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    actor_a = "11111111-1111-1111-1111-111111111111"
    bystander = "33333333-3333-3333-3333-333333333333"

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception", user_id=actor_a)
    await _insert_audit_row(rls_conn, tenant_id, actor_a)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="professional", user_id=bystander)
    rows = (await rls_conn.execute(sa.text("SELECT id FROM audit_logs"))).all()
    assert rows == []


async def test_audit_logs_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    actor_id = "11111111-1111-1111-1111-111111111111"

    await set_app_context(rls_conn, tenant_id=tenant_b, role="reception", user_id=actor_id)
    await _insert_audit_row(rls_conn, tenant_b, actor_id)

    await set_app_context(rls_conn, tenant_id=tenant_a, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM audit_logs"))).all()
    assert rows == []
