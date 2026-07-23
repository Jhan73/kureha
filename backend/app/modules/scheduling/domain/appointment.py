"""`Appointment` domain (design.md §4.1's `appointments` table shape). Pure
value object -- state-transition invariants only, no IO. The actual write
(the `EXCLUDE USING gist` anti double-booking constraint, §4.1) lives at the
Postgres adapter/schema layer; this class only knows whether a given instance
is currently in an active (mutable) state."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.modules.scheduling.domain.errors import AppointmentNotActiveError


class AppointmentStatus(str, Enum):
    """Mirrors `appointments.status`'s CHECK constraint exactly (design.md
    §4.1)."""

    SCHEDULED = "scheduled"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


_ACTIVE_STATUSES = frozenset({AppointmentStatus.SCHEDULED, AppointmentStatus.RESCHEDULED})


@dataclass(frozen=True, slots=True)
class Appointment:
    id: str
    tenant_id: str
    site_id: str
    patient_id: str
    professional_id: str
    availability_id: str
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus

    @property
    def is_active(self) -> bool:
        """`scheduled`/`rescheduled` are the only statuses the `EXCLUDE
        USING gist` constraint (design.md §4.1) itself checks against for
        overlap -- an appointment outside this set is a closed record
        (cancelled/completed/no-show), never eligible for reschedule/cancel
        again."""
        return self.status in _ACTIVE_STATUSES

    def ensure_active(self) -> None:
        """Raises `AppointmentNotActiveError` unless `is_active` -- the
        precondition `RescheduleAppointment`/`CancelAppointment` (tasks.md
        7.3) share before attempting a state transition."""
        if not self.is_active:
            raise AppointmentNotActiveError(f"Appointment {self.id} is not active (status={self.status.value})")
