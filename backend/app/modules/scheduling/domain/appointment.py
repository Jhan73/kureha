from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.modules.scheduling.domain.errors import AppointmentNotActiveError


class AppointmentStatus(str, Enum):
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
        """Only scheduled/rescheduled participate in overlap checks."""
        return self.status in _ACTIVE_STATUSES

    def ensure_active(self) -> None:
        """Precondition for reschedule/cancel."""
        if not self.is_active:
            raise AppointmentNotActiveError(f"Appointment {self.id} is not active (status={self.status.value})")
