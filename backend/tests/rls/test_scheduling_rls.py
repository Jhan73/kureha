"""Task 2.9: RLS isolation for availability/appointments (design.md §4.2's
worked example, migration 613f9ea3526f)."""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from tests.rls.helpers import (
    seed_appointment,
    seed_availability,
    seed_patient,
    seed_professional,
    seed_site,
    seed_tenant,
    set_app_context,
)
from tests.schema.helpers import expect_violation

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)


async def test_availability_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    professional_b = await seed_professional(rls_conn, tenant_b, site_b)
    await seed_availability(rls_conn, tenant_b, site_b, professional_b, starts_at=T0, ends_at=T1)

    site_a = await seed_site(rls_conn, tenant_a)
    await set_app_context(rls_conn, tenant_id=tenant_a, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM availability"))).all()
    assert rows == []


async def test_availability_cross_site_returns_zero_rows(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    professional_b = await seed_professional(rls_conn, tenant_id, site_b)
    await seed_availability(rls_conn, tenant_id, site_b, professional_b, starts_at=T0, ends_at=T1)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM availability"))).all()
    assert rows == []


async def test_availability_professional_cannot_write_another_professionals_slot(rls_conn) -> None:
    """Fixed in review: `availability_staff` previously had no
    `professional_id` check, so any professional/reception/admin at a site
    could write ANY professional's slots at that site.
    `availability_professional` now mirrors `appointments_professional`'s
    shape -- a professional may only manage their own availability."""
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_a = await seed_professional(rls_conn, tenant_id, site_id, name="A")
    professional_b = await seed_professional(rls_conn, tenant_id, site_id, name="B")

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_id, role="professional", professional_id=professional_a
    )
    async with expect_violation(rls_conn, DBAPIError, match="row-level security"):
        await rls_conn.execute(
            sa.text(
                "INSERT INTO availability (tenant_id, site_id, professional_id, starts_at, ends_at) "
                "VALUES (:t, :s, :p, :starts_at, :ends_at)"
            ),
            {"t": tenant_id, "s": site_id, "p": professional_b, "starts_at": T0, "ends_at": T1},
        )


async def test_availability_reception_can_write_any_professionals_slot_at_site(rls_conn) -> None:
    """Guards the fix above against over-correcting: splitting
    `availability_staff` into `availability_reception`/
    `availability_professional` must not lock reception/admin out of the
    site-wide access they had before."""
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    result = await rls_conn.execute(
        sa.text(
            "INSERT INTO availability (tenant_id, site_id, professional_id, starts_at, ends_at) "
            "VALUES (:t, :s, :p, :starts_at, :ends_at) RETURNING id"
        ),
        {"t": tenant_id, "s": site_id, "p": professional_id, "starts_at": T0, "ends_at": T1},
    )
    assert result.scalar_one() is not None


async def test_appointments_reception_sees_own_site_only(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    professional_a = await seed_professional(rls_conn, tenant_id, site_a)
    professional_b = await seed_professional(rls_conn, tenant_id, site_b)
    patient_a = await seed_patient(rls_conn, tenant_id, site_a)
    patient_b = await seed_patient(rls_conn, tenant_id, site_b)
    avail_a = await seed_availability(rls_conn, tenant_id, site_a, professional_a, starts_at=T0, ends_at=T1)
    avail_b = await seed_availability(rls_conn, tenant_id, site_b, professional_b, starts_at=T0, ends_at=T1)
    appointment_a = await seed_appointment(
        rls_conn, tenant_id, site_a, patient_a, professional_a, avail_a, starts_at=T0, ends_at=T1
    )
    await seed_appointment(
        rls_conn, tenant_id, site_b, patient_b, professional_b, avail_b, starts_at=T0, ends_at=T1
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM appointments"))).all()
    assert [str(row.id) for row in rows] == [appointment_a]


async def test_appointments_professional_sees_only_their_own(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_a = await seed_professional(rls_conn, tenant_id, site_id, name="A")
    professional_b = await seed_professional(rls_conn, tenant_id, site_id, name="B")
    patient_a = await seed_patient(rls_conn, tenant_id, site_id, document_number="A1")
    patient_b = await seed_patient(rls_conn, tenant_id, site_id, document_number="B1")
    avail_a = await seed_availability(rls_conn, tenant_id, site_id, professional_a, starts_at=T0, ends_at=T1)
    avail_b = await seed_availability(
        rls_conn, tenant_id, site_id, professional_b, starts_at=T1, ends_at=T2
    )
    appointment_a = await seed_appointment(
        rls_conn, tenant_id, site_id, patient_a, professional_a, avail_a, starts_at=T0, ends_at=T1
    )
    await seed_appointment(
        rls_conn,
        tenant_id,
        site_id,
        patient_b,
        professional_b,
        avail_b,
        starts_at=T1,
        ends_at=T2,
    )

    await set_app_context(
        rls_conn, tenant_id=tenant_id, site_id=site_id, role="professional", professional_id=professional_a
    )
    rows = (await rls_conn.execute(sa.text("SELECT id FROM appointments"))).all()
    assert [str(row.id) for row in rows] == [appointment_a]


async def test_appointments_patient_sees_only_their_own_regardless_of_site(rls_conn) -> None:
    tenant_id = await seed_tenant(rls_conn)
    site_a = await seed_site(rls_conn, tenant_id, name="Site A")
    site_b = await seed_site(rls_conn, tenant_id, name="Site B")
    professional_a = await seed_professional(rls_conn, tenant_id, site_a)
    professional_b = await seed_professional(rls_conn, tenant_id, site_b)
    patient_a = await seed_patient(rls_conn, tenant_id, site_a, document_number="A1")
    patient_b = await seed_patient(rls_conn, tenant_id, site_b, document_number="B1")
    avail_a = await seed_availability(rls_conn, tenant_id, site_a, professional_a, starts_at=T0, ends_at=T1)
    avail_b = await seed_availability(rls_conn, tenant_id, site_b, professional_b, starts_at=T0, ends_at=T1)
    appointment_a = await seed_appointment(
        rls_conn, tenant_id, site_a, patient_a, professional_a, avail_a, starts_at=T0, ends_at=T1
    )
    await seed_appointment(
        rls_conn, tenant_id, site_b, patient_b, professional_b, avail_b, starts_at=T0, ends_at=T1
    )

    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_b, role="patient", patient_id=patient_a)
    rows = (await rls_conn.execute(sa.text("SELECT id FROM appointments"))).all()
    assert [str(row.id) for row in rows] == [appointment_a]


async def test_appointments_cross_tenant_select_returns_zero_rows(rls_conn) -> None:
    tenant_a = await seed_tenant(rls_conn)
    tenant_b = await seed_tenant(rls_conn)
    site_b = await seed_site(rls_conn, tenant_b)
    professional_b = await seed_professional(rls_conn, tenant_b, site_b)
    patient_b = await seed_patient(rls_conn, tenant_b, site_b)
    avail_b = await seed_availability(rls_conn, tenant_b, site_b, professional_b, starts_at=T0, ends_at=T1)
    await seed_appointment(
        rls_conn, tenant_b, site_b, patient_b, professional_b, avail_b, starts_at=T0, ends_at=T1
    )

    site_a = await seed_site(rls_conn, tenant_a)
    await set_app_context(rls_conn, tenant_id=tenant_a, site_id=site_a, role="reception")
    rows = (await rls_conn.execute(sa.text("SELECT id FROM appointments"))).all()
    assert rows == []
