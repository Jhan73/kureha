import pytest
import sqlalchemy as sa

from tests.rls.helpers import seed_patient, seed_professional, seed_site, seed_tenant, seed_user, set_app_context
from tests.schema.helpers import expect_violation


async def _seed_cross_tenant_site(conn, tenant_id) -> None:
    await seed_site(conn, tenant_id, name="Tenant B Site")


async def _seed_cross_tenant_professional(conn, tenant_id) -> None:
    site_id = await seed_site(conn, tenant_id)
    await seed_professional(conn, tenant_id, site_id)


async def _seed_cross_tenant_user(conn, tenant_id) -> None:
    site_id = await seed_site(conn, tenant_id)
    await seed_user(conn, tenant_id, site_id, role="admin")


async def _seed_cross_tenant_patient(conn, tenant_id) -> None:
    site_id = await seed_site(conn, tenant_id)
    await seed_patient(conn, tenant_id, site_id)


@pytest.mark.parametrize(
    "table, seed_cross_tenant_row, context_role, context_needs_site",
    [
        ("sites", _seed_cross_tenant_site, "admin", False),
        ("professionals", _seed_cross_tenant_professional, "reception", True),
        ("users", _seed_cross_tenant_user, "admin", True),
        ("patients", _seed_cross_tenant_patient, "reception", True),
    ],
)
async def test_cross_tenant_select_returns_zero_rows(
    rls_conn, table, seed_cross_tenant_row, context_role, context_needs_site
) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    await seed_cross_tenant_row(rls_conn, tenant_b)

    site_a = await seed_site(rls_conn, tenant_a) if context_needs_site else None
    await set_app_context(rls_conn, tenant_id=tenant_a, site_id=site_a, role=context_role)
    rows = (await rls_conn.execute(sa.text(f"SELECT id FROM {table}"))).all()
    assert rows == []


async def test_sites_same_tenant_any_role_can_select(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM sites"))).all()
    assert [str(row.id) for row in rows] == [site_id]


async def test_sites_non_admin_cannot_insert(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="reception")
    async with expect_violation(rls_conn, Exception, match="row-level security"):
        await rls_conn.execute(
            sa.text("INSERT INTO sites (tenant_id, name) VALUES (:t, 'Rogue Site')"),
            {"t": tenant_id},
        )


async def test_professionals_cross_site_same_tenant_returns_zero_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    await seed_professional(rls_conn, tenant_id, site_b)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM professionals"))).all()
    assert rows == []


async def test_users_self_select_sees_own_row_only(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_a = await seed_professional(rls_conn, tenant_id, site_id, name="A")
    professional_b = await seed_professional(rls_conn, tenant_id, site_id, name="B")
    self_id = await seed_user(rls_conn, tenant_id, site_id, role="professional", professional_id=professional_a)
    await seed_user(rls_conn, tenant_id, site_id, role="professional", professional_id=professional_b)

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_id, role="professional", user_id=self_id
    )
    rows = (await rls_conn.execute(sa.text("SELECT id FROM users"))).all()
    assert [str(row.id) for row in rows] == [self_id]


async def test_users_reception_sees_full_site_directory(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    reception_id = await seed_user(rls_conn, tenant_id, site_id, role="reception")
    professional_user_id = await seed_user(
        rls_conn, tenant_id, site_id, role="professional", professional_id=professional_id
    )

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception", user_id=reception_id
    )
    rows = (await rls_conn.execute(sa.text("SELECT id FROM users"))).all()
    ids = {str(row.id) for row in rows}
    assert ids == {reception_id, professional_user_id}


async def test_users_professional_cannot_see_other_users(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    self_id = await seed_user(
        rls_conn, tenant_id, site_id, role="professional", professional_id=professional_id
    )
    await seed_user(rls_conn, tenant_id, site_id, role="reception")

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_id, role="professional", user_id=self_id
    )
    rows = (await rls_conn.execute(sa.text("SELECT id FROM users"))).all()
    assert [str(row.id) for row in rows] == [self_id]


async def test_patients_staff_can_write_and_see_null_site_patient(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await rls_conn.execute(
        sa.text(
            "INSERT INTO patients (tenant_id, site_id, name, document_number) "
            "VALUES (:t, NULL, 'No Site Patient', 'DNI-NOSITE') RETURNING id"
        ),
        {"t": tenant_id},
    )
    patient_id = str(result.scalar_one())

    rows = (await rls_conn.execute(sa.text("SELECT id FROM patients"))).all()
    assert [str(row.id) for row in rows] == [patient_id]


async def test_patients_staff_sees_only_own_site(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    patient_a = await seed_patient(rls_conn, tenant_id, site_a)
    await seed_patient(rls_conn, tenant_id, site_b)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM patients"))).all()
    assert [str(row.id) for row in rows] == [patient_a]


async def test_patients_self_sees_only_own_record_regardless_of_site(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    patient_id = await seed_patient(rls_conn, tenant_id, site_a)
    await seed_patient(rls_conn, tenant_id, site_b)

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_b, role="patient", patient_id=patient_id
    )
    rows = (await rls_conn.execute(sa.text("SELECT id FROM patients"))).all()
    assert [str(row.id) for row in rows] == [patient_id]
