from typing import Protocol

from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord


class CalendarSyncRepositoryPort(Protocol):
    async def get_by_appointment(self, tenant_id: str, appointment_id: str) -> CalendarSyncRecord | None: ...

    async def get_or_create(
        self, tenant_id: str, site_id: str, appointment_id: str, *, idempotency_key: str
    ) -> CalendarSyncRecord:
        """Idempotent get-or-create keyed on appointment_id (one row reused across attempts)."""
        ...

    async def mark_ok(self, tenant_id: str, appointment_id: str, *, google_event_id: str) -> CalendarSyncRecord:
        """Sets ok + google_event_id; clears last_error; does not touch attempts."""
        ...

    async def mark_failed(self, tenant_id: str, appointment_id: str, *, error: str) -> CalendarSyncRecord:
        """Sets failed, increments attempts, stores last_error."""
        ...

    async def list_due_for_retry(self, tenant_id: str, *, max_attempts: int) -> list[CalendarSyncRecord]:
        """pending/failed with attempts < max_attempts; backoff policy decides due timing."""
        ...
