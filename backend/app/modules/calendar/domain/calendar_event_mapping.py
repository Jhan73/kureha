"""`CalendarEventMapping`: calendar-module's own view of "one appointment,
as a Google Calendar event" (design.md §2.5's folder comment: "mapeo cita
<-> evento") -- deliberately NOT `scheduling.Appointment` (business modules
never import each other's internals, backend/AGENTS.md); callers translate
their own appointment data into this shape before calling `CalendarSyncPort`.

`CalendarSyncResult` mirrors design.md §7.1's port docstring exactly:
`{ok, google_event_id, error}`."""

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
