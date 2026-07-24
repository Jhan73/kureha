"""`AppointmentSnapshotPort` (design.md §7.5, tasks.md task 9.5): calendar's
own narrow driven port for the minimal appointment data the RETRY job needs
to rebuild a `CalendarEventMapping` without holding the original
just-committed `Appointment` object (unlike `SyncAppointmentToCalendar`'s
normal post-commit call, which receives that data directly from its caller
-- the retry job runs independently later, with only a `calendar_sync` row's
`appointment_id` to start from).

`scheduling` owns `Appointment`; calendar never imports it directly
(business modules never import each other's internals, backend/AGENTS.md).
Mirrors `StaffStatusPort`'s exact pattern (application/ports/driven/
staff_status_port.py in `modules.scheduling`): the module that needs the
read defines its own port, shaped around its own vocabulary. The concrete
adapter is deliberately left unbuilt here -- see
`adapters/outbound/appointment_snapshot/unwired_adapter.py`'s docstring for
the same "open composition-root seam" tasks.md task 8.4 already established
this precedent for."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AppointmentSyncSnapshot:
    patient_id: str
    starts_at: datetime
    ends_at: datetime
    site_id: str | None = None
    """Added tasks.md task 11.5 (PR 11 batch 3, `platform/inbound/graph/
    nodes/calendar_sync.py`): that graph node needs `site_id` to call
    `SyncAppointmentToCalendar.execute(..., site_id=...)` for the FIRST sync
    of a just-created appointment, where (unlike `RetryPendingCalendarSyncs`
    above) no `calendar_sync` row exists yet to read `site_id` off of.
    Optional and unused by `RetryPendingCalendarSyncs` (it already has
    `record.site_id` from the `calendar_sync` row itself) -- kept optional
    rather than required so this remains a strictly additive, non-breaking
    change to an existing port."""


class AppointmentSnapshotPort(Protocol):
    async def get_snapshot(self, tenant_id: str, appointment_id: str) -> AppointmentSyncSnapshot | None:
        """Returns the CURRENT patient/time-window for `appointment_id`
        (reflecting any reschedule since the original sync attempt), or
        `None` if the appointment no longer exists."""
        ...
