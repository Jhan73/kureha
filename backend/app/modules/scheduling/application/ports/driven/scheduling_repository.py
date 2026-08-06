from datetime import datetime
from typing import Protocol

from app.modules.scheduling.domain.appointment import Appointment


class SchedulingRepositoryPort(Protocol):
    async def create_appointment(
        self,
        tenant_id: str,
        *,
        site_id: str,
        patient_id: str,
        professional_id: str,
        availability_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> Appointment:
        """Inserts status='scheduled'; raises SlotUnavailableError on EXCLUDE conflict."""
        ...

    async def get_appointment(self, tenant_id: str, appointment_id: str) -> Appointment | None:
        """Tenant-scoped PK lookup; None if missing or RLS-hidden."""
        ...

    async def reschedule_appointment(
        self,
        tenant_id: str,
        appointment_id: str,
        *,
        professional_id: str,
        availability_id: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> Appointment:
        """Moves slot/professional; same SlotUnavailableError as create."""
        ...

    async def cancel_appointment(self, tenant_id: str, appointment_id: str) -> Appointment:
        """Sets status='cancelled'; never deletes."""
        ...
