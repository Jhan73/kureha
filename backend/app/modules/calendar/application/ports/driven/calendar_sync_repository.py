"""`CalendarSyncRepositoryPort` (design.md §4.4/§7.2/§7.5, tasks.md task 9.4):
calendar-module's own driven port over `calendar_sync`. Implemented in MVP
by `PostgresCalendarSyncRepository` (adapters/outbound/postgres/
calendar_sync_repository.py).

**RLS note:** `calendar_sync`'s only policy, `calendar_sync_staff` (migration
613f9ea3526f), requires `app.role IN ('reception','professional','admin')`
-- staff-only, no patient-self path. See `calendar_credential_repository.py`'s
docstring for why this and `CalendarCredentialRepositoryPort`'s
patient-only policy cannot both be satisfied by ONE `app.role` value within
`SyncAppointmentToCalendar`'s single flow -- flagged for the Phase 10
composition root, not resolved here."""

from typing import Protocol

from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord


class CalendarSyncRepositoryPort(Protocol):
    async def get_by_appointment(self, tenant_id: str, appointment_id: str) -> CalendarSyncRecord | None: ...

    async def get_or_create(
        self, tenant_id: str, site_id: str, appointment_id: str, *, idempotency_key: str
    ) -> CalendarSyncRecord:
        """Idempotent get-or-create keyed on `appointment_id` (`UNIQUE
        (appointment_id)`, migration 00d985a7bfa5) -- the SAME row is reused
        across an appointment's create/reschedule/cancel sync attempts, not
        a new row per attempt."""
        ...

    async def mark_ok(self, tenant_id: str, appointment_id: str, *, google_event_id: str) -> CalendarSyncRecord:
        """Sets `sync_status='ok'`, stores `google_event_id`, clears
        `last_error` -- does NOT touch `attempts` (design.md §7.2:
        `attempts` counts failures, not attempts)."""
        ...

    async def mark_failed(self, tenant_id: str, appointment_id: str, *, error: str) -> CalendarSyncRecord:
        """Sets `sync_status='failed'`, increments `attempts`, stores
        `last_error` (design.md §7.2)."""
        ...

    async def list_due_for_retry(self, tenant_id: str, *, max_attempts: int) -> list[CalendarSyncRecord]:
        """Returns every `pending`/`failed` row with `attempts < max_attempts`
        for the tenant -- the retry job's own `RetryBackoffPolicy` (domain/
        retry_backoff_policy.py) decides WHICH of these are actually due
        right now from `updated_at`/`attempts`; this method only applies the
        cheap status+cap filter design.md §7.5 describes ("reintenta
        `sync_status IN ('pending','failed')`... tope de `attempts`")."""
        ...
