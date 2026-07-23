"""`RetryPendingCalendarSyncs` (design.md §7.5, tasks.md task 9.5): the
bounded retry/reconciliation job over `pending`/`failed` `calendar_sync`
rows. Composes `RetryBackoffPolicy` (domain, pure) for the backoff/attempts-
cap decision and delegates the actual re-attempt to `SyncAppointmentToCalendar`
(application/use_cases/sync_appointment_to_calendar.py) -- this job's own
job is orchestration (which rows are due, refresh their appointment data),
not re-implementing the sync/mark-result logic a second time.

`AppointmentSnapshotPort` exists because this job runs independently, later,
with only a `calendar_sync` row's `appointment_id` to start from -- unlike
`SyncAppointmentToCalendar`'s normal post-commit call, which receives fresh
appointment data directly from its caller (see that port's docstring).

If the target appointment no longer exists at all (`get_snapshot` returns
`None` -- should not happen in practice given `appointments` has no hard
delete, but defensive), this job marks the row permanently `failed` via
`mark_failed` directly, WITHOUT calling `SyncAppointmentToCalendar` (nothing
meaningful to sync)."""

from app.modules.calendar.application.ports.driven.appointment_snapshot import AppointmentSnapshotPort
from app.modules.calendar.application.ports.driven.calendar_sync_repository import CalendarSyncRepositoryPort
from app.modules.calendar.application.use_cases.sync_appointment_to_calendar import SyncAppointmentToCalendar
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord
from app.modules.calendar.domain.retry_backoff_policy import RetryBackoffPolicy
from app.shared_kernel.clock import ClockPort


class RetryPendingCalendarSyncs:
    def __init__(
        self,
        calendar_sync_repository: CalendarSyncRepositoryPort,
        appointment_snapshot: AppointmentSnapshotPort,
        sync_appointment: SyncAppointmentToCalendar,
        backoff_policy: RetryBackoffPolicy,
        clock: ClockPort,
    ) -> None:
        self._calendar_sync_repository = calendar_sync_repository
        self._appointment_snapshot = appointment_snapshot
        self._sync_appointment = sync_appointment
        self._backoff_policy = backoff_policy
        self._clock = clock

    async def execute(self, tenant_id: str) -> list[CalendarSyncRecord]:
        candidates = await self._calendar_sync_repository.list_due_for_retry(
            tenant_id, max_attempts=self._backoff_policy.max_attempts
        )
        now = self._clock.now()
        results: list[CalendarSyncRecord] = []

        for record in candidates:
            if not self._backoff_policy.is_due(attempts=record.attempts, updated_at=record.updated_at, now=now):
                continue

            snapshot = await self._appointment_snapshot.get_snapshot(tenant_id, record.appointment_id)
            if snapshot is None:
                results.append(
                    await self._calendar_sync_repository.mark_failed(
                        tenant_id, record.appointment_id, error="appointment_not_found"
                    )
                )
                continue

            results.append(
                await self._sync_appointment.execute(
                    tenant_id,
                    site_id=record.site_id,
                    appointment_id=record.appointment_id,
                    patient_id=snapshot.patient_id,
                    starts_at=snapshot.starts_at,
                    ends_at=snapshot.ends_at,
                )
            )

        return results
