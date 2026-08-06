import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from app.modules.governance.audit.adapters.outbound.postgres.audit_log import PostgresAuditLog
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from tests.rls.helpers import seed_tenant, set_app_context
from tests.schema.helpers import expect_violation


async def test_record_inserts_a_row_and_returns_its_id(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    actor_id = "11111111-1111-1111-1111-111111111111"
    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception", user_id=actor_id)

    audit_log = PostgresAuditLog(rls_conn)
    entry = AuditEntry(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=AuditActorType.USER,
        action=AuditAction.APPOINTMENT_CREATE,
        object_type="appointment",
        payload={"result": "success"},
    )

    row_id = await audit_log.record(entry)

    assert row_id is not None

    row = (
        await rls_conn.execute(
            sa.text("SELECT action, row_hash, prev_hash, payload FROM audit_logs WHERE id = :id"),
            {"id": row_id},
        )
    ).one()
    assert row.action == "appointment.create"
    assert row.row_hash is not None
    assert row.prev_hash is None  # first row for this tenant
    assert row.payload == {"result": "success"}


async def test_record_populates_hash_chain_across_two_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")

    audit_log = PostgresAuditLog(rls_conn)
    first_id = await audit_log.record(
        AuditEntry(
            tenant_id=tenant_id,
            actor_type=AuditActorType.SYSTEM,
            action=AuditAction.CONSENT_BLOCK,
            object_type="consent",
        )
    )
    await audit_log.record(
        AuditEntry(
            tenant_id=tenant_id,
            actor_type=AuditActorType.SYSTEM,
            action=AuditAction.SCOPE_ESCALATE,
            object_type="chat",
        )
    )

    first_hash = (
        await rls_conn.execute(sa.text("SELECT row_hash FROM audit_logs WHERE id = :id"), {"id": first_id})
    ).scalar_one()
    second_prev_hash = (
        await rls_conn.execute(
            sa.text("SELECT prev_hash FROM audit_logs WHERE action = 'scope.escalate' AND tenant_id = :t"),
            {"t": tenant_id},
        )
    ).scalar_one()
    assert second_prev_hash == first_hash


async def test_record_cross_tenant_rejected_by_rls(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    await set_app_context(rls_conn, tenant_id=tenant_a, role="reception")

    audit_log = PostgresAuditLog(rls_conn)
    async with expect_violation(rls_conn, DBAPIError, match="row-level security"):
        await audit_log.record(
            AuditEntry(
                tenant_id=tenant_b,
                actor_type=AuditActorType.USER,
                action=AuditAction.APPOINTMENT_CANCEL,
                object_type="appointment",
            )
        )
