"""Task 2.9: RLS isolation for consent_policies/consents (migration
613f9ea3526f, same tenant-wide-self shape as patients)."""

import sqlalchemy as sa

from tests.rls.helpers import seed_consent, seed_consent_policy, seed_patient, seed_site, seed_tenant, set_app_context


async def test_consent_policies_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    await seed_consent_policy(rls_conn, tenant_b)

    await set_app_context(rls_conn, tenant_id=tenant_a, role="admin")
    rows = (await rls_conn.execute(sa.text("SELECT tenant_id FROM consent_policies"))).all()
    assert rows == []


async def test_consent_policies_any_role_can_select_within_tenant(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await seed_consent_policy(rls_conn, tenant_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient")
    rows = (await rls_conn.execute(sa.text("SELECT version FROM consent_policies"))).all()
    assert [row.version for row in rows] == ["2026.1"]


async def test_consents_staff_sees_only_own_site(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    await seed_consent_policy(rls_conn, tenant_id)
    patient_a = await seed_patient(rls_conn, tenant_id, site_a)
    patient_b = await seed_patient(rls_conn, tenant_id, site_b)
    consent_a = await seed_consent(rls_conn, tenant_id, site_a, patient_a)
    await seed_consent(rls_conn, tenant_id, site_b, patient_b)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM consents"))).all()
    assert [str(row.id) for row in rows] == [consent_a]


async def test_consents_staff_can_write_and_see_null_site_consent(rls_conn) -> None:
    """Fixed in review: `consents_staff`'s implicit WITH CHECK previously
    required `site_id` to exactly match `app.site_id`, rejecting a legitimate
    INSERT of a site-less consent (`consents.site_id` is nullable, same class
    of gap as `patients_staff` -- see migration docstring point 8). Staff at
    ANY site in the tenant can now see/write a site-less consent."""
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    await seed_consent_policy(rls_conn, tenant_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await rls_conn.execute(
        sa.text(
            "INSERT INTO consents "
            "(tenant_id, site_id, patient_id, policy_version, status, document_hash, channel, accepted_at) "
            "VALUES (:t, NULL, :patient, '2026.1', 'accepted', 'hash', 'web', now()) RETURNING id"
        ),
        {"t": tenant_id, "patient": patient_id},
    )
    consent_id = str(result.scalar_one())

    rows = (await rls_conn.execute(sa.text("SELECT id FROM consents"))).all()
    assert [str(row.id) for row in rows] == [consent_id]


async def test_consents_patient_sees_only_their_own_regardless_of_site(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    await seed_consent_policy(rls_conn, tenant_id)
    patient_a = await seed_patient(rls_conn, tenant_id, site_a, document_number="A1")
    patient_b = await seed_patient(rls_conn, tenant_id, site_b, document_number="B1")
    consent_a = await seed_consent(rls_conn, tenant_id, site_a, patient_a)
    await seed_consent(rls_conn, tenant_id, site_b, patient_b)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_b, role="patient", patient_id=patient_a)
    rows = (await rls_conn.execute(sa.text("SELECT id FROM consents"))).all()
    assert [str(row.id) for row in rows] == [consent_a]


async def test_consents_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    await seed_consent_policy(rls_conn, tenant_b)
    patient_b = await seed_patient(rls_conn, tenant_b, site_b)
    await seed_consent(rls_conn, tenant_b, site_b, patient_b)

    site_a = await seed_site(rls_conn, tenant_a)
    await set_app_context(rls_conn, tenant_id=tenant_a, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM consents"))).all()
    assert rows == []
