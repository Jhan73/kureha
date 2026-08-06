from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from tests.rls.helpers import (
    seed_appointment,
    seed_availability,
    seed_calendar_credential,
    seed_calendar_sync,
    seed_patient,
    seed_professional,
    seed_site,
    seed_tenant,
    set_app_context,
)

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)


async def test_calendar_credentials_patient_sees_only_their_own(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    patient_a = await seed_patient(rls_conn, tenant_id, site_id, document_number="A1")
    patient_b = await seed_patient(rls_conn, tenant_id, site_id, document_number="B1")
    credential_a = await seed_calendar_credential(rls_conn, tenant_id, patient_a)
    await seed_calendar_credential(rls_conn, tenant_id, patient_b)

    await set_app_context(rls_conn, tenant_id=tenant_id, role="patient", patient_id=patient_a)
    rows = (await rls_conn.execute(sa.text("SELECT id FROM calendar_credentials"))).all()
    assert [str(row.id) for row in rows] == [credential_a]


async def test_calendar_credentials_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    patient_b = await seed_patient(rls_conn, tenant_b, site_b)
    await seed_calendar_credential(rls_conn, tenant_b, patient_b)

    await set_app_context(rls_conn, tenant_id=tenant_a, role="patient", patient_id=patient_b)
    rows = (await rls_conn.execute(sa.text("SELECT id FROM calendar_credentials"))).all()
    assert rows == []


async def test_calendar_sync_staff_cross_site_returns_zero_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    professional_b = await seed_professional(rls_conn, tenant_id, site_b)
    patient_b = await seed_patient(rls_conn, tenant_id, site_b)
    avail_b = await seed_availability(rls_conn, tenant_id, site_b, professional_b, starts_at=T0, ends_at=T1)
    appointment_b = await seed_appointment(
        rls_conn, tenant_id, site_b, patient_b, professional_b, avail_b, starts_at=T0, ends_at=T1
    )
    await seed_calendar_sync(rls_conn, tenant_id, site_b, appointment_b, idempotency_key="kureha-b")

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM calendar_sync"))).all()
    assert rows == []


async def test_calendar_sync_staff_same_site_can_select(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    avail_id = await seed_availability(rls_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T1)
    appointment_id = await seed_appointment(
        rls_conn, tenant_id, site_id, patient_id, professional_id, avail_id, starts_at=T0, ends_at=T1
    )
    sync_id = await seed_calendar_sync(rls_conn, tenant_id, site_id, appointment_id, idempotency_key="kureha-a")

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM calendar_sync"))).all()
    assert [str(row.id) for row in rows] == [sync_id]
