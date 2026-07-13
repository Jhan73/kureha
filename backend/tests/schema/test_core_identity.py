"""Task 2.1: tenants, sites, users, professionals, patients (design.md §4.1).

`patients` identity is tenant-wide, not site-wide (design.md §4.1 rationale):
the same document_number must be allowed to register at two different sites
of the same tenant would be a duplicate -> UNIQUE(tenant_id, document_number),
NOT UNIQUE(site_id, document_number).
"""

import sqlalchemy as sa

from tests.schema.helpers import expect_violation, make_patient, make_professional, make_site, make_tenant


async def test_patient_document_number_unique_within_tenant(db_conn, tenant_id) -> None:
    await make_patient(db_conn, tenant_id, document_number="12345678")

    async with expect_violation(db_conn):
        await make_patient(db_conn, tenant_id, document_number="12345678")


async def test_patient_document_number_may_repeat_across_tenants(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)

    id_a = await make_patient(db_conn, tenant_a, document_number="99999999")
    id_b = await make_patient(db_conn, tenant_b, document_number="99999999")

    assert id_a != id_b


async def test_patient_site_id_is_nullable_registration_site(db_conn, tenant_id) -> None:
    patient_id = await make_patient(db_conn, tenant_id, site_id=None)

    row = (
        await db_conn.execute(
            sa.text("SELECT site_id FROM patients WHERE id = :id"), {"id": patient_id}
        )
    ).one()
    assert row.site_id is None


async def test_tenants_status_check_rejects_unknown_value(db_conn) -> None:
    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text("INSERT INTO tenants (name, status) VALUES ('X', 'bogus')")
        )


async def test_user_role_patient_requires_patient_id(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO users (tenant_id, site_id, role) "
                "VALUES (:tenant_id, :site_id, 'patient')"
            ),
            {"tenant_id": tenant_id, "site_id": site_id},
        )


async def test_user_role_patient_with_patient_id_succeeds(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    patient_id = await make_patient(db_conn, tenant_id, site_id=site_id)

    result = await db_conn.execute(
        sa.text(
            "INSERT INTO users (tenant_id, site_id, role, patient_id) "
            "VALUES (:tenant_id, :site_id, 'patient', :patient_id) RETURNING id"
        ),
        {"tenant_id": tenant_id, "site_id": site_id, "patient_id": patient_id},
    )
    assert result.scalar_one() is not None


async def test_user_role_professional_requires_professional_id(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO users (tenant_id, site_id, role) "
                "VALUES (:tenant_id, :site_id, 'professional')"
            ),
            {"tenant_id": tenant_id, "site_id": site_id},
        )


async def test_user_role_reception_needs_neither_patient_nor_professional_id(
    db_conn, tenant_id
) -> None:
    site_id = await make_site(db_conn, tenant_id)

    result = await db_conn.execute(
        sa.text(
            "INSERT INTO users (tenant_id, site_id, role) "
            "VALUES (:tenant_id, :site_id, 'reception') RETURNING id"
        ),
        {"tenant_id": tenant_id, "site_id": site_id},
    )
    assert result.scalar_one() is not None


async def test_professional_site_id_must_belong_to_same_tenant(db_conn) -> None:
    """Composite FK (tenant_id, site_id) -> sites(tenant_id, id): a site from
    a different tenant must not be assignable (design.md §4.2 relies on
    tenant_id/site_id never disagreeing)."""
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_of_b = await make_site(db_conn, tenant_b)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO professionals (tenant_id, site_id, name) "
                "VALUES (:tenant_id, :site_id, 'X')"
            ),
            {"tenant_id": tenant_a, "site_id": site_of_b},
        )


async def test_patient_site_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_of_b = await make_site(db_conn, tenant_b)

    async with expect_violation(db_conn):
        await make_patient(db_conn, tenant_a, site_id=site_of_b)


async def test_user_patient_id_must_belong_to_same_tenant(db_conn) -> None:
    """users.patient_id now has a composite FK (tenant_id, patient_id) ->
    patients(tenant_id, id): a patient from a different tenant must not be
    assignable to a user."""
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    patient_of_b = await make_patient(db_conn, tenant_b)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO users (tenant_id, site_id, role, patient_id) "
                "VALUES (:tenant_id, :site_id, 'patient', :patient_id)"
            ),
            {"tenant_id": tenant_a, "site_id": site_a, "patient_id": patient_of_b},
        )


async def test_user_professional_id_must_belong_to_same_tenant(db_conn) -> None:
    tenant_a = await make_tenant(db_conn)
    tenant_b = await make_tenant(db_conn)
    site_a = await make_site(db_conn, tenant_a)
    site_b = await make_site(db_conn, tenant_b)
    professional_of_b = await make_professional(db_conn, tenant_b, site_b)

    async with expect_violation(db_conn):
        await db_conn.execute(
            sa.text(
                "INSERT INTO users (tenant_id, site_id, role, professional_id) "
                "VALUES (:tenant_id, :site_id, 'professional', :professional_id)"
            ),
            {
                "tenant_id": tenant_a,
                "site_id": site_a,
                "professional_id": professional_of_b,
            },
        )


async def test_professional_belongs_to_tenant_and_site(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)

    professional_id = await make_professional(db_conn, tenant_id, site_id)

    row = (
        await db_conn.execute(
            sa.text("SELECT tenant_id, site_id FROM professionals WHERE id = :id"),
            {"id": professional_id},
        )
    ).one()
    assert str(row.tenant_id) == tenant_id
    assert str(row.site_id) == site_id
