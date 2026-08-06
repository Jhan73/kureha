from typing import Protocol

from app.modules.calendar.domain.calendar_credential import CalendarCredential
from app.modules.calendar.domain.calendar_event_mapping import CalendarEventMapping, CalendarSyncResult


class CalendarSyncPort(Protocol):
    async def upsert_event(self, cred: CalendarCredential, mapping: CalendarEventMapping) -> CalendarSyncResult:
        """Create or update by idempotency_key — same key must not duplicate events."""
        ...

    async def delete_event(self, cred: CalendarCredential, google_event_id: str) -> CalendarSyncResult:
        """Delete event; already-gone id is idempotent success."""
        ...
