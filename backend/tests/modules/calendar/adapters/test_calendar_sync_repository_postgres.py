"""Task 9.4/9.5: `PostgresCalendarSyncRepository` -- `CalendarSyncRepositoryPort`
adapter over `calendar_sync` (design.md §4.4/§7.2/§7.5, migration
00d985a7bfa5). Uses `rls_conn` scoped as staff (`calendar_sync_staff` is the
only policy on this table, migration 613f9ea3526f)."""

from datetime import datetime, timedelta, timezone

from tests.rls.helpers import (
    seed_appointment,
    seed_availability,
    seed_patient,
    seed_professional,
    seed_site,
    seed_tenant,
    set_app_context,
)

from app.modules.calendar.adapters.outbound.postgres.calendar_sync_repository import PostgresCalendarSyncRepository
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncStatus
from app.modules.calendar.domain.idempotency import derive_idempotency_key

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = _T0 + timedelta(hours=1)


async def _seed_appointment(rls_conn) -> tuple[str, str, str]:
    tenant_id = await seed_tenant(rls_conn)
    site_id = await seed_site(rls_conn, tenant_id)
    professional_id = await seed_professional(rls_conn, tenant_id, site_id)
    patient_id = await seed_patient(rls_conn, tenant_id, site_id)
    availability_id = await seed_availability(rls_conn, tenant_id, site_id, professional_id, starts_at=_T0, ends_at=_T1)
    appointment_id = await seed_appointment(
        rls_conn, tenant_id, site_id, patient_id, professional_id, availability_id, starts_at=_T0, ends_at=_T1
    )
    await set_app_context(rls_conn, tenant_id=tenant_id, site_id=site_id, role="reception")
    return tenant_id, site_id, appointment_id


async def test_get_by_appointment_returns_none_when_never_synced(rls_conn) -> None:
    tenant_id, _site_id, appointment_id = await _seed_appointment(rls_conn)
    repository = PostgresCalendarSyncRepository(rls_conn)

    assert await repository.get_by_appointment(tenant_id, appointment_id) is None


async def test_get_or_create_inserts_a_pending_row(rls_conn) -> None:
    tenant_id, site_id, appointment_id = await _seed_appointment(rls_conn)
    repository = PostgresCalendarSyncRepository(rls_conn)
    key = derive_idempotency_key(appointment_id)

    record = await repository.get_or_create(tenant_id, site_id, appointment_id, idempotency_key=key)

    assert record.status == CalendarSyncStatus.PENDING
    assert record.attempts == 0
    assert record.idempotency_key == key
    assert record.appointment_id == appointment_id


async def test_get_or_create_is_idempotent_and_returns_the_same_row(rls_conn) -> None:
    tenant_id, site_id, appointment_id = await _seed_appointment(rls_conn)
    repository = PostgresCalendarSyncRepository(rls_conn)
    key = derive_idempotency_key(appointment_id)

    first = await repository.get_or_create(tenant_id, site_id, appointment_id, idempotency_key=key)
    second = await repository.get_or_create(tenant_id, site_id, appointment_id, idempotency_key=key)

    assert first.id == second.id


async def test_mark_ok_sets_status_and_google_event_id(rls_conn) -> None:
    tenant_id, site_id, appointment_id = await _seed_appointment(rls_conn)
    repository = PostgresCalendarSyncRepository(rls_conn)
    key = derive_idempotency_key(appointment_id)
    await repository.get_or_create(tenant_id, site_id, appointment_id, idempotency_key=key)

    updated = await repository.mark_ok(tenant_id, appointment_id, google_event_id=key)

    assert updated.status == CalendarSyncStatus.OK
    assert updated.google_event_id == key
    assert updated.last_error is None


async def test_mark_failed_increments_attempts_and_records_the_error(rls_conn) -> None:
    tenant_id, site_id, appointment_id = await _seed_appointment(rls_conn)
    repository = PostgresCalendarSyncRepository(rls_conn)
    key = derive_idempotency_key(appointment_id)
    await repository.get_or_create(tenant_id, site_id, appointment_id, idempotency_key=key)

    first_fail = await repository.mark_failed(tenant_id, appointment_id, error="quota_exceeded")
    second_fail = await repository.mark_failed(tenant_id, appointment_id, error="quota_exceeded")

    assert first_fail.status == CalendarSyncStatus.FAILED
    assert first_fail.attempts == 1
    assert first_fail.last_error == "quota_exceeded"
    assert second_fail.attempts == 2


async def test_list_due_for_retry_filters_by_status_and_attempts_cap(rls_conn) -> None:
    tenant_id, site_id, appointment_id = await _seed_appointment(rls_conn)
    repository = PostgresCalendarSyncRepository(rls_conn)
    key = derive_idempotency_key(appointment_id)
    await repository.get_or_create(tenant_id, site_id, appointment_id, idempotency_key=key)
    await repository.mark_failed(tenant_id, appointment_id, error="x")

    below_cap = await repository.list_due_for_retry(tenant_id, max_attempts=5)
    at_cap = await repository.list_due_for_retry(tenant_id, max_attempts=1)

    assert [r.appointment_id for r in below_cap] == [appointment_id]
    assert at_cap == []


async def test_list_due_for_retry_excludes_ok_rows(rls_conn) -> None:
    tenant_id, site_id, appointment_id = await _seed_appointment(rls_conn)
    repository = PostgresCalendarSyncRepository(rls_conn)
    key = derive_idempotency_key(appointment_id)
    await repository.get_or_create(tenant_id, site_id, appointment_id, idempotency_key=key)
    await repository.mark_ok(tenant_id, appointment_id, google_event_id=key)

    due = await repository.list_due_for_retry(tenant_id, max_attempts=5)

    assert due == []
