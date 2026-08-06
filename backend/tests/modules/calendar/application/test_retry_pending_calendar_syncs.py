from datetime import datetime, timedelta, timezone

from app.modules.calendar.application.ports.driven.appointment_snapshot import AppointmentSyncSnapshot
from app.modules.calendar.application.use_cases.retry_pending_calendar_syncs import RetryPendingCalendarSyncs
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord, CalendarSyncStatus
from app.modules.calendar.domain.idempotency import derive_idempotency_key
from app.modules.calendar.domain.retry_backoff_policy import RetryBackoffPolicy

_NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_APPT_A = "9c858901-8a57-4791-81fe-4c455b099bc9"
_APPT_B = "1e6b2f9e-4d3a-4b7a-9c1e-2f6a8b9c0d1e"


def _record(appointment_id: str, *, attempts: int = 0, updated_at: datetime = _NOW) -> CalendarSyncRecord:
    return CalendarSyncRecord(
        id=f"sync-{appointment_id}",
        tenant_id="t1",
        site_id="s1",
        appointment_id=appointment_id,
        idempotency_key=derive_idempotency_key(appointment_id),
        status=CalendarSyncStatus.FAILED,
        attempts=attempts,
        updated_at=updated_at,
        google_event_id=None,
        last_error="quota_exceeded",
    )


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


class _FakeCalendarSyncRepository:
    def __init__(self, *, due: list[CalendarSyncRecord]) -> None:
        self._due = due
        self.mark_failed_calls: list[dict] = []

    async def get_by_appointment(self, tenant_id, appointment_id):
        raise NotImplementedError

    async def get_or_create(self, tenant_id, site_id, appointment_id, *, idempotency_key):
        raise NotImplementedError

    async def mark_ok(self, tenant_id, appointment_id, *, google_event_id):
        raise NotImplementedError

    async def mark_failed(self, tenant_id, appointment_id, *, error):
        self.mark_failed_calls.append({"appointment_id": appointment_id, "error": error})
        return _record(appointment_id, attempts=99)

    async def list_due_for_retry(self, tenant_id, *, max_attempts):
        return self._due


class _FakeAppointmentSnapshot:
    def __init__(self, snapshots: dict[str, AppointmentSyncSnapshot | None]) -> None:
        self._snapshots = snapshots
        self.queried: list[str] = []

    async def get_snapshot(self, tenant_id, appointment_id):
        self.queried.append(appointment_id)
        return self._snapshots.get(appointment_id)


class _FakeSyncAppointmentToCalendar:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def execute(self, tenant_id, *, site_id, appointment_id, patient_id, starts_at, ends_at, **kwargs):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "appointment_id": appointment_id,
                "patient_id": patient_id,
                "starts_at": starts_at,
                "ends_at": ends_at,
            }
        )
        return _record(appointment_id, attempts=1)


def _snapshot() -> AppointmentSyncSnapshot:
    return AppointmentSyncSnapshot(patient_id="p1", starts_at=_NOW, ends_at=_NOW + timedelta(hours=1))


async def test_retries_only_records_past_their_backoff_window() -> None:
    not_due_yet = _record(_APPT_A, attempts=0, updated_at=_NOW)  # backoff 60s, "now" == updated_at
    due = _record(_APPT_B, attempts=0, updated_at=_NOW - timedelta(seconds=120))
    sync_repo = _FakeCalendarSyncRepository(due=[not_due_yet, due])
    snapshots = _FakeAppointmentSnapshot({_APPT_A: _snapshot(), _APPT_B: _snapshot()})
    sync_appointment = _FakeSyncAppointmentToCalendar()
    job = RetryPendingCalendarSyncs(
        sync_repo, snapshots, sync_appointment, RetryBackoffPolicy(base_seconds=60, max_attempts=5), _FakeClock(_NOW)
    )

    await job.execute("t1")

    assert sync_appointment.calls == [
        {
            "tenant_id": "t1",
            "site_id": "s1",
            "appointment_id": _APPT_B,
            "patient_id": "p1",
            "starts_at": _NOW,
            "ends_at": _NOW + timedelta(hours=1),
        }
    ]


async def test_missing_appointment_marks_failed_permanently_without_calling_sync() -> None:
    due = _record(_APPT_A, attempts=0, updated_at=_NOW - timedelta(seconds=120))
    sync_repo = _FakeCalendarSyncRepository(due=[due])
    snapshots = _FakeAppointmentSnapshot({_APPT_A: None})
    sync_appointment = _FakeSyncAppointmentToCalendar()
    job = RetryPendingCalendarSyncs(
        sync_repo, snapshots, sync_appointment, RetryBackoffPolicy(base_seconds=60, max_attempts=5), _FakeClock(_NOW)
    )

    await job.execute("t1")

    assert sync_appointment.calls == []
    assert sync_repo.mark_failed_calls == [{"appointment_id": _APPT_A, "error": "appointment_not_found"}]


async def test_uses_the_policys_max_attempts_for_the_repository_query() -> None:
    sync_repo = _FakeCalendarSyncRepository(due=[])
    snapshots = _FakeAppointmentSnapshot({})
    sync_appointment = _FakeSyncAppointmentToCalendar()
    captured: list[int] = []

    async def list_due_for_retry(tenant_id, *, max_attempts):
        captured.append(max_attempts)
        return []

    sync_repo.list_due_for_retry = list_due_for_retry  # type: ignore[method-assign]
    job = RetryPendingCalendarSyncs(
        sync_repo, snapshots, sync_appointment, RetryBackoffPolicy(base_seconds=60, max_attempts=3), _FakeClock(_NOW)
    )

    await job.execute("t1")

    assert captured == [3]
