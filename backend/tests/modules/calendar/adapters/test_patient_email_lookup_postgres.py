"""Task 9.4: `PostgresPatientEmailLookup` -- `PatientEmailLookupPort` adapter
reading `patients.email` (design.md §7.3, migration 8fc0dc6f958d). Uses
`rls_conn` scoped as `role='patient'` (the `patients_self` policy, migration
613f9ea3526f) -- matches how `ConnectPatientCalendar` actually runs."""

from sqlalchemy import text

from tests.rls.helpers import seed_patient, seed_site, seed_tenant, set_app_context

from app.modules.calendar.adapters.outbound.postgres.patient_email_lookup import PostgresPatientEmailLookup


async def test_get_registered_email_returns_the_patients_email(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    await rls_conn.execute(
        text("UPDATE patients SET email = :email WHERE id = :id"), {"email": "a@example.com", "id": patient_id}
    )
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    lookup = PostgresPatientEmailLookup(rls_conn)

    assert await lookup.get_registered_email(tenant_id, patient_id) == "a@example.com"


async def test_get_registered_email_returns_none_when_no_email_on_file(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_id)
    lookup = PostgresPatientEmailLookup(rls_conn)

    assert await lookup.get_registered_email(tenant_id, patient_id) is None


async def test_get_registered_email_returns_none_for_unknown_patient(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    await set_app_context(
        rls_conn, tenant_id=tenant_id, role="patient", patient_id="00000000-0000-0000-0000-000000000000"
    )
    lookup = PostgresPatientEmailLookup(rls_conn)

    assert await lookup.get_registered_email(tenant_id, "00000000-0000-0000-0000-000000000000") is None
