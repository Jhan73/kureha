import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.schema.helpers import expect_violation, make_site, make_tenant


async def _insert_audit_row(conn, tenant_id, *, action="appointment.create", object_id=None):
    result = await conn.execute(
        sa.text(
            "INSERT INTO audit_logs (tenant_id, actor_type, action, object_type, object_id) "
            "VALUES (:tenant_id, 'system', :action, 'appointment', :object_id) "
            "RETURNING id, seq, prev_hash, row_hash"
        ),
        {"tenant_id": tenant_id, "action": action, "object_id": object_id},
    )
    return result.one()


async def test_audit_logs_reject_update(db_conn, tenant_id) -> None:
    row = await _insert_audit_row(db_conn, tenant_id)

    async with expect_violation(db_conn, DBAPIError, match="append-only"):
        await db_conn.execute(
            sa.text("UPDATE audit_logs SET action = 'tampered' WHERE id = :id"),
            {"id": row.id},
        )


async def test_audit_logs_reject_delete(db_conn, tenant_id) -> None:
    row = await _insert_audit_row(db_conn, tenant_id)

    async with expect_violation(db_conn, DBAPIError, match="append-only"):
        await db_conn.execute(
            sa.text("DELETE FROM audit_logs WHERE id = :id"), {"id": row.id}
        )


async def test_audit_logs_reject_truncate(db_conn, tenant_id) -> None:
    await _insert_audit_row(db_conn, tenant_id)

    async with expect_violation(db_conn, DBAPIError, match="append-only"):
        await db_conn.execute(sa.text("TRUNCATE audit_logs"))


async def test_first_row_of_a_tenant_chain_has_null_prev_hash(db_conn, tenant_id) -> None:
    row = await _insert_audit_row(db_conn, tenant_id)

    assert row.prev_hash is None
    assert row.row_hash is not None


async def test_hash_chain_links_consecutive_rows_within_tenant(db_conn, tenant_id) -> None:
    row1 = await _insert_audit_row(db_conn, tenant_id, action="appointment.create")
    row2 = await _insert_audit_row(db_conn, tenant_id, action="appointment.reschedule")
    row3 = await _insert_audit_row(db_conn, tenant_id, action="appointment.cancel")

    assert row2.prev_hash == row1.row_hash
    assert row3.prev_hash == row2.row_hash
    assert len({row1.row_hash, row2.row_hash, row3.row_hash}) == 3


async def test_hash_chain_does_not_span_tenants(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)

    await _insert_audit_row(db_conn, tenant_a, action="appointment.create")
    row_b1 = await _insert_audit_row(db_conn, tenant_b, action="appointment.create")

    assert row_b1.prev_hash is None


async def test_hash_chain_row_hash_matches_canonical_recomputation(db_conn, tenant_id) -> None:
    await _insert_audit_row(db_conn, tenant_id, action="appointment.create")
    await _insert_audit_row(db_conn, tenant_id, action="appointment.reschedule")
    await _insert_audit_row(db_conn, tenant_id, action="appointment.cancel")

    mismatches = (
        await db_conn.execute(
            sa.text(
                """
                WITH chain AS (
                    SELECT
                        row_hash,
                        prev_hash,
                        tenant_id,
                        actor_type,
                        action,
                        object_id,
                        payload,
                        ts,
                        LAG(row_hash) OVER (PARTITION BY tenant_id ORDER BY seq) AS expected_prev
                    FROM audit_logs
                    WHERE tenant_id = :tenant_id
                )
                SELECT count(*) AS mismatches
                FROM chain
                WHERE row_hash <> encode(
                    digest(
                        coalesce(expected_prev, '') || '|' ||
                        tenant_id::text || '|' || actor_type || '|' || action || '|' ||
                        coalesce(object_id::text, '') || '|' ||
                        payload::text || '|' || ts::text,
                        'sha256'
                    ),
                    'hex'
                )
                OR prev_hash IS DISTINCT FROM expected_prev
                """
            ),
            {"tenant_id": tenant_id},
        )
    ).scalar_one()

    assert mismatches == 0


async def test_audit_logs_actor_type_check_rejects_unknown_value(db_conn, tenant_id) -> None:
    async with expect_violation(db_conn, DBAPIError):
        await db_conn.execute(
            sa.text(
                "INSERT INTO audit_logs (tenant_id, actor_type, action, object_type) "
                "VALUES (:tenant_id, 'bogus', 'appointment.create', 'appointment')"
            ),
            {"tenant_id": tenant_id},
        )


async def test_audit_logs_site_id_rejects_a_site_from_a_different_tenant(db_conn, tenant_id) -> None:
    other_tenant_id = await make_tenant(db_conn)
    other_tenants_site_id = await make_site(db_conn, other_tenant_id)

    async with expect_violation(db_conn, IntegrityError):
        await db_conn.execute(
            sa.text(
                "INSERT INTO audit_logs (tenant_id, site_id, actor_type, action, object_type) "
                "VALUES (:tenant_id, :site_id, 'system', 'appointment.create', 'appointment')"
            ),
            {"tenant_id": tenant_id, "site_id": other_tenants_site_id},
        )


async def test_audit_logs_site_id_accepts_a_site_from_the_same_tenant(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)

    result = await db_conn.execute(
        sa.text(
            "INSERT INTO audit_logs (tenant_id, site_id, actor_type, action, object_type) "
            "VALUES (:tenant_id, :site_id, 'system', 'appointment.create', 'appointment') "
            "RETURNING id"
        ),
        {"tenant_id": tenant_id, "site_id": site_id},
    )
    assert result.scalar_one() is not None
