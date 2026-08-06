from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CalendarEventMapping:
    appointment_id: str
    idempotency_key: str
    starts_at: datetime
    ends_at: datetime
    summary: str


@dataclass(frozen=True, slots=True)
class CalendarSyncResult:
    ok: bool
    google_event_id: str | None = None
    error: str | None = None
