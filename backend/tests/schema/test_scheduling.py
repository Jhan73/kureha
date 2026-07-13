"""Task 2.2: availability, appointments (design.md §4.1).

Anti double-booking is enforced in Postgres itself via
`EXCLUDE USING gist`, not in application code -> these are constraint tests,
not use-case tests (no domain/use-case layer exists yet, per tasks.md Phase 3+).
"""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from tests.schema.helpers import (
    expect_violation,
    make_patient,
    make_professional,
    make_site,
    make_tenant,
)

T0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)


async def _make_availability(
    conn, tenant_id, site_id, professional_id, *, starts_at, ends_at, status="available"
):
    return await conn.execute(
        sa.text(
            "INSERT INTO availability "
            "(tenant_id, site_id, professional_id, starts_at, ends_at, status) "
            "VALUES (:tenant_id, :site_id, :professional_id, :starts_at, :ends_at, :status) "
            "RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "professional_id": professional_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": status,
        },
    )


async def _make_appointment(
    conn,
    tenant_id,
    site_id,
    patient_id,
    professional_id,
    availability_id,
    *,
    starts_at,
    ends_at,
    status="scheduled",
):
    return await conn.execute(
        sa.text(
            "INSERT INTO appointments "
            "(tenant_id, site_id, patient_id, professional_id, availability_id, "
            " starts_at, ends_at, status) "
            "VALUES (:tenant_id, :site_id, :patient_id, :professional_id, :availability_id, "
            " :starts_at, :ends_at, :status) RETURNING id"
        ),
        {
            "tenant_id": tenant_id,
            "site_id": site_id,
            "patient_id": patient_id,
            "professional_id": professional_id,
            "availability_id": availability_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": status,
        },
    )


async def test_availability_check_ends_after_starts(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)

    async with expect_violation(db_conn):
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0,
            ends_at=T0 - timedelta(hours=1),
        )


async def test_availability_rejects_overlap_same_professional(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)

    await _make_availability(
        db_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T0 + timedelta(hours=1)
    )

    async with expect_violation(db_conn):
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0 + timedelta(minutes=30),
            ends_at=T0 + timedelta(hours=2),
        )


async def test_availability_site_id_must_belong_to_same_tenant(db_conn, tenant_id) -> None:
    tenant_b = await make_tenant(db_conn)
    site_of_b = await make_site(db_conn, tenant_b)
    professional_a = await make_professional(db_conn, tenant_id, await make_site(db_conn, tenant_id))

    async with expect_violation(db_conn):
        await _make_availability(
            db_conn,
            tenant_id,
            site_of_b,
            professional_a,
            starts_at=T0,
            ends_at=T0 + timedelta(hours=1),
        )


async def test_appointments_check_ends_after_starts(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    patient_id = await make_patient(db_conn, tenant_id, site_id=site_id)
    slot_id = (
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0,
            ends_at=T0 + timedelta(hours=1),
        )
    ).scalar_one()

    async with expect_violation(db_conn):
        await _make_appointment(
            db_conn,
            tenant_id,
            site_id,
            patient_id,
            professional_id,
            slot_id,
            starts_at=T0,
            ends_at=T0,
        )


async def test_availability_allows_non_overlapping_slots(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)

    await _make_availability(
        db_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T0 + timedelta(hours=1)
    )
    result = await _make_availability(
        db_conn,
        tenant_id,
        site_id,
        professional_id,
        starts_at=T0 + timedelta(hours=1),
        ends_at=T0 + timedelta(hours=2),
    )
    assert result.scalar_one() is not None


async def test_availability_allows_overlap_across_different_professionals(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    prof_a = await make_professional(db_conn, tenant_id, site_id, name="A")
    prof_b = await make_professional(db_conn, tenant_id, site_id, name="B")

    await _make_availability(
        db_conn, tenant_id, site_id, prof_a, starts_at=T0, ends_at=T0 + timedelta(hours=1)
    )
    result = await _make_availability(
        db_conn, tenant_id, site_id, prof_b, starts_at=T0, ends_at=T0 + timedelta(hours=1)
    )
    assert result.scalar_one() is not None


async def test_appointments_reject_double_booking_same_professional(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    patient_a = await make_patient(db_conn, tenant_id, site_id=site_id)
    patient_b = await make_patient(db_conn, tenant_id, site_id=site_id)

    slot_a = (
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0,
            ends_at=T0 + timedelta(hours=1),
        )
    ).scalar_one()
    slot_b = (
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0 + timedelta(hours=1),
            ends_at=T0 + timedelta(hours=2),
        )
    ).scalar_one()

    await _make_appointment(
        db_conn,
        tenant_id,
        site_id,
        patient_a,
        professional_id,
        slot_a,
        starts_at=T0,
        ends_at=T0 + timedelta(hours=1),
    )

    async with expect_violation(db_conn):
        await _make_appointment(
            db_conn,
            tenant_id,
            site_id,
            patient_b,
            professional_id,
            slot_b,
            starts_at=T0 + timedelta(minutes=30),
            ends_at=T0 + timedelta(hours=1, minutes=30),
        )


async def test_appointments_allow_overlap_when_prior_is_cancelled(db_conn, tenant_id) -> None:
    """The EXCLUDE constraint is scoped to active statuses (design.md §4.1):
    `WHERE (status IN ('scheduled','rescheduled'))` -> a cancelled slot must
    not block a new booking over the same time range."""
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    patient_a = await make_patient(db_conn, tenant_id, site_id=site_id)
    patient_b = await make_patient(db_conn, tenant_id, site_id=site_id)

    slot_a = (
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0,
            ends_at=T0 + timedelta(hours=1),
        )
    ).scalar_one()
    slot_b = (
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0 + timedelta(hours=1),
            ends_at=T0 + timedelta(hours=2),
        )
    ).scalar_one()

    await _make_appointment(
        db_conn,
        tenant_id,
        site_id,
        patient_a,
        professional_id,
        slot_a,
        starts_at=T0,
        ends_at=T0 + timedelta(hours=1),
        status="cancelled",
    )

    result = await _make_appointment(
        db_conn,
        tenant_id,
        site_id,
        patient_b,
        professional_id,
        slot_b,
        starts_at=T0,
        ends_at=T0 + timedelta(hours=1),
        status="scheduled",
    )
    assert result.scalar_one() is not None


async def test_appointments_status_check_rejects_unknown_value(db_conn, tenant_id) -> None:
    site_id = await make_site(db_conn, tenant_id)
    professional_id = await make_professional(db_conn, tenant_id, site_id)
    patient_id = await make_patient(db_conn, tenant_id, site_id=site_id)
    slot_id = (
        await _make_availability(
            db_conn,
            tenant_id,
            site_id,
            professional_id,
            starts_at=T0,
            ends_at=T0 + timedelta(hours=1),
        )
    ).scalar_one()

    async with expect_violation(db_conn):
        await _make_appointment(
            db_conn,
            tenant_id,
            site_id,
            patient_id,
            professional_id,
            slot_id,
            starts_at=T0,
            ends_at=T0 + timedelta(hours=1),
            status="bogus",
        )
