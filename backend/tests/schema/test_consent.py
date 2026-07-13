"""Task 2.3: consent_policies, consents (design.md §4.1, §11).

Both tables are tenant-scoped (not site-scoped): a clinic (tenant) is its own
legal entity and owns one current consent policy version regardless of which
site a patient was registered at.
"""

import sqlalchemy as sa

from tests.schema.helpers import expect_violation, make_patient, make_site, make_tenant


async def _make_policy(conn, tenant_id, *, version, is_current, document_hash="deadbeef"):
    return await conn.execute(
        sa.text(
            "INSERT INTO consent_policies (tenant_id, version, document_hash, is_current) "
            "VALUES (:tenant_id, :version, :document_hash, :is_current)"
        ),
        {
            "tenant_id": tenant_id,
            "version": version,
            "document_hash": document_hash,
            "is_current": is_current,
        },
    )


async def _make_consent(
    conn,
    tenant_id,
    patient_id,
    *,
    policy_version,
    status="accepted",
    accepted_at="now()",
    revoked_at=None,
):
    """`accepted_at`/`revoked_at` default to satisfying the status/timestamp
    CHECK for the common case (accepted -> accepted_at set; revoked ->
    also pass revoked_at). Pass `accepted_at=None` explicitly to test the
    CHECK's rejection path."""
    if status == "revoked" and revoked_at is None:
        revoked_at = "now()"
    accepted_expr = "now()" if accepted_at == "now()" else ":accepted_at"
    revoked_expr = "now()" if revoked_at == "now()" else ":revoked_at"
    return await conn.execute(
        sa.text(
            "INSERT INTO consents "
            "(tenant_id, patient_id, policy_version, status, document_hash, channel, "
            " accepted_at, revoked_at) "
            f"VALUES (:tenant_id, :patient_id, :policy_version, :status, 'deadbeef', 'web', "
            f" {accepted_expr}, {revoked_expr}) "
            "RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "patient_id": patient_id,
            "policy_version": policy_version,
            "status": status,
            **({"accepted_at": accepted_at} if accepted_expr == ":accepted_at" else {}),
            **({"revoked_at": revoked_at} if revoked_expr == ":revoked_at" else {}),
        },
    )


async def test_only_one_current_policy_per_tenant(db_conn, tenant_id) -> None:
    await _make_policy(db_conn, tenant_id, version="2026.1", is_current=True)

    async with expect_violation(db_conn):
        await _make_policy(db_conn, tenant_id, version="2026.2", is_current=True)


async def test_multiple_non_current_policies_allowed(db_conn, tenant_id) -> None:
    await _make_policy(db_conn, tenant_id, version="2025.1", is_current=False)
    await _make_policy(db_conn, tenant_id, version="2025.2", is_current=False)
    # no exception raised


async def test_current_policy_may_repeat_across_tenants(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)

    await _make_policy(db_conn, tenant_a, version="2026.1", is_current=True)
    await _make_policy(db_conn, tenant_b, version="2026.1", is_current=True)
    # no exception raised: unique index is scoped by tenant_id


async def test_consent_requires_existing_policy_version_for_same_tenant(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)

    async with expect_violation(db_conn):
        await _make_consent(db_conn, tenant_id, patient_id, policy_version="nonexistent")


async def test_consent_with_valid_policy_version_succeeds(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)
    await _make_policy(db_conn, tenant_id, version="2026.1", is_current=True)

    result = await _make_consent(db_conn, tenant_id, patient_id, policy_version="2026.1")
    assert result.scalar_one() is not None


async def test_consent_status_check_rejects_unknown_value(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)
    await _make_policy(db_conn, tenant_id, version="2026.1", is_current=True)

    async with expect_violation(db_conn):
        await _make_consent(
            db_conn, tenant_id, patient_id, policy_version="2026.1", status="bogus"
        )


async def test_consent_site_id_must_belong_to_same_tenant(db_conn, tenant_id) -> None:
    tenant_b = await make_tenant(db_conn)
    site_of_b = await make_site(db_conn, tenant_b)
    patient_a = await make_patient(db_conn, tenant_id)
    await _make_policy(db_conn, tenant_id, version="2026.1", is_current=True)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO consents "
                "(tenant_id, site_id, patient_id, policy_version, status, "
                " document_hash, channel, accepted_at) "
                "VALUES (:tenant_id, :site_id, :patient_id, '2026.1', 'accepted', "
                " 'deadbeef', 'web', now())"
            ),
            {"tenant_id": tenant_id, "site_id": site_of_b, "patient_id": patient_a},
        )


async def test_consent_accepted_requires_accepted_at(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)
    await _make_policy(db_conn, tenant_id, version="2026.1", is_current=True)

    async with expect_violation(db_conn):
        await _make_consent(
            db_conn, tenant_id, patient_id, policy_version="2026.1", accepted_at=None
        )


async def test_consent_revoked_requires_both_timestamps(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)
    await _make_policy(db_conn, tenant_id, version="2026.1", is_current=True)

    async with expect_violation(db_conn):
        await _make_consent(
            db_conn,
            tenant_id,
            patient_id,
            policy_version="2026.1",
            status="revoked",
            accepted_at=None,
        )


async def test_consent_revoked_with_both_timestamps_succeeds(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id)
    await _make_policy(db_conn, tenant_id, version="2026.1", is_current=True)

    result = await _make_consent(
        db_conn, tenant_id, patient_id, policy_version="2026.1", status="revoked"
    )
    assert result.scalar_one() is not None


async def test_consent_policy_version_scoped_by_tenant_not_reusable_cross_tenant(db_conn) -> None:
    """A policy version that exists for tenant A must not satisfy the FK for
    a consent recorded under tenant B (design.md §4.1: composite FK on
    (tenant_id, policy_version))."""
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    patient_b = await make_patient(db_conn, tenant_b)
    await _make_policy(db_conn, tenant_a, version="2026.1", is_current=True)

    async with expect_violation(db_conn):
        await _make_consent(db_conn, tenant_b, patient_b, policy_version="2026.1")
