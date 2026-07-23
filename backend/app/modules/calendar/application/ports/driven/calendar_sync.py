"""`CalendarSyncPort` (design.md §7.1, tasks.md task 9.1): the driven port
`SyncAppointmentToCalendar` depends on to mirror an appointment mutation
into Google Calendar. Implemented in MVP by `GoogleCalendarAdapter`
(adapters/outbound/calendar/google_calendar_adapter.py).

Both methods are UPSERT-shaped by contract, not raise-on-failure: a Google
API failure (timeout, auth error, quota, 5xx, ...) is reported back as
`CalendarSyncResult(ok=False, error=...)`, never as a raised exception --
callers (design.md §7.2's best-effort/non-transactional contract) must never
have to catch an unbounded exception type from this port to stay non-
blocking. See `CalendarSyncResult`'s own docstring."""

from typing import Protocol

from app.modules.calendar.domain.calendar_credential import CalendarCredential
from app.modules.calendar.domain.calendar_event_mapping import CalendarEventMapping, CalendarSyncResult


class CalendarSyncPort(Protocol):
    async def upsert_event(self, cred: CalendarCredential, mapping: CalendarEventMapping) -> CalendarSyncResult:
        """Creates the event if `mapping.idempotency_key` does not exist yet
        for this calendar, or updates it in place (reschedule) if it does --
        design.md §7.6's ADR-18: retried with the SAME `idempotency_key`,
        this MUST NOT create a duplicate event."""
        ...

    async def delete_event(self, cred: CalendarCredential, google_event_id: str) -> CalendarSyncResult:
        """Deletes the event. Deleting an already-deleted/never-created event
        id is a no-op success (idempotent), not an error."""
        ...
