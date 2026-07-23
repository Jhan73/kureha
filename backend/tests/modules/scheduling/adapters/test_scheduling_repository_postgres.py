"""Task 7.4: `PostgresSchedulingRepository` -- `SchedulingRepositoryPort`
adapter over `appointments` (design.md §4.1, migration 3505dc8ce3ad).

Uses `rls_conn` (the `app_runtime`/RLS-enforced connection), same contract
as `PostgresAvailabilityRepository`'s test module."""

from datetime import datetime, timedelta, timezone

import pytest

from tests.rls.helpers import seed_availability, seed_patient, seed_professional, seed_site, seed_tenant, set_app_context

from app.modules.scheduling.adapters.outbound.postgres.scheduling_repository import PostgresSchedulingRepository
from app.modules.scheduling.domain.appointment import AppointmentStatus
from app.modules.scheduling.domain.errors import SlotUnavailableError

T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
T2 = T0 + timedelta(hours=2)


async def _seed_scenario(rls_conn):
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    availability_id = await seed_availability(rls_conn, tenant_id, site_id, professional_id, starts_at=T0, ends_at=T1)
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    return tenant_id, site_id, professional_id, patient_id, availability_id


async def test_create_appointment_inserts_a_scheduled_row(rls_conn) -> None:
    tenant_id, site_id, professional_id, patient_id, availability_id = await _seed_scenario(rls_conn)
    repository = PostgresSchedulingRepository(rls_conn)

    appointment = await repository.create_appointment(
        tenant_id,
        site_id=site_id,
        patient_id=patient_id,
        professional_id=professional_id,
        availability_id=availability_id,
        starts_at=T0,
        ends_at=T1,
    )

    assert appointment.tenant_id == tenant_id
    assert appointment.site_id == site_id
    assert appointment.patient_id == patient_id
    assert appointment.professional_id == professional_id
    assert appointment.availability_id == availability_id
    assert appointment.status == AppointmentStatus.SCHEDULED


async def test_create_appointment_raises_slot_unavailable_on_overlap(rls_conn) -> None:
    """Two DIFFERENT (non-overlapping-with-each-other) `availability` rows
    for the SAME professional, but the second `create_appointment` call is
    given overlapping `starts_at`/`ends_at` -- this hits `appointments`'
    own `EXCLUDE USING gist` (design.md §4.1), independent of whatever
    range each row's `availability_id` was originally published for."""
    tenant_id, site_id, professional_id, patient_id, availability_id = await _seed_scenario(rls_conn)
    other_availability = await seed_availability(
        rls_conn, tenant_id, site_id, professional_id, starts_at=T2, ends_at=T2 + timedelta(hours=1)
    )
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    repository = PostgresSchedulingRepository(rls_conn)

    async with rls_conn.begin_nested():
        await repository.create_appointment(
            tenant_id, site_id=site_id, patient_id=patient_id, professional_id=professional_id,
            availability_id=availability_id, starts_at=T0, ends_at=T1,
        )

    with pytest.raises(SlotUnavailableError):
        async with rls_conn.begin_nested():
            await repository.create_appointment(
                tenant_id, site_id=site_id, patient_id=patient_id, professional_id=professional_id,
                availability_id=other_availability, starts_at=T0 + timedelta(minutes=30), ends_at=T1 + timedelta(minutes=30),
            )


async def test_get_appointment_returns_the_appointment(rls_conn) -> None:
    tenant_id, site_id, professional_id, patient_id, availability_id = await _seed_scenario(rls_conn)
    repository = PostgresSchedulingRepository(rls_conn)
    created = await repository.create_appointment(
        tenant_id, site_id=site_id, patient_id=patient_id, professional_id=professional_id,
        availability_id=availability_id, starts_at=T0, ends_at=T1,
    )

    fetched = await repository.get_appointment(tenant_id, created.id)

    assert fetched == created


async def test_get_appointment_returns_none_for_unknown_id(rls_conn) -> None:
    tenant_id, *_ = await _seed_scenario(rls_conn)
    repository = PostgresSchedulingRepository(rls_conn)

    assert await repository.get_appointment(tenant_id, "00000000-0000-0000-0000-000000000000") is None


async def test_cancel_appointment_sets_status_cancelled(rls_conn) -> None:
    tenant_id, site_id, professional_id, patient_id, availability_id = await _seed_scenario(rls_conn)
    repository = PostgresSchedulingRepository(rls_conn)
    created = await repository.create_appointment(
        tenant_id, site_id=site_id, patient_id=patient_id, professional_id=professional_id,
        availability_id=availability_id, starts_at=T0, ends_at=T1,
    )

    cancelled = await repository.cancel_appointment(tenant_id, created.id)

    assert cancelled.status == AppointmentStatus.CANCELLED
    assert cancelled.id == created.id


async def test_reschedule_appointment_moves_slot_and_professional(rls_conn) -> None:
    tenant_id, site_id, professional_id, patient_id, availability_id = await _seed_scenario(rls_conn)
    other_professional = await seed_professional(rls_conn, tenant_id, site_id, name="Other")
    new_availability = await seed_availability(
        rls_conn, tenant_id, site_id, other_professional, starts_at=T1, ends_at=T2
    )
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")

    repository = PostgresSchedulingRepository(rls_conn)
    created = await repository.create_appointment(
        tenant_id, site_id=site_id, patient_id=patient_id, professional_id=professional_id,
        availability_id=availability_id, starts_at=T0, ends_at=T1,
    )

    rescheduled = await repository.reschedule_appointment(
        tenant_id, created.id,
        professional_id=other_professional, availability_id=new_availability, starts_at=T1, ends_at=T2,
    )

    assert rescheduled.status == AppointmentStatus.RESCHEDULED
    assert rescheduled.professional_id == other_professional
    assert rescheduled.availability_id == new_availability
    assert rescheduled.starts_at == T1
    assert rescheduled.ends_at == T2
