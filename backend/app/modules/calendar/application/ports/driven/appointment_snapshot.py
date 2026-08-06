from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AppointmentSyncSnapshot:
    patient_id: str
    starts_at: datetime
    ends_at: datetime
    site_id: str | None = None


class AppointmentSnapshotPort(Protocol):
    async def get_snapshot(self, tenant_id: str, appointment_id: str) -> AppointmentSyncSnapshot | None:
        """Current patient/time window (post-reschedule), or None if gone."""
        ...
