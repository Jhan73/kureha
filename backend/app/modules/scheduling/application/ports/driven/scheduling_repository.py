"""`SchedulingRepositoryPort` (design.md §4.1): `appointments` access for the
scheduling module's use cases. Implemented in MVP by
`PostgresSchedulingRepository` (adapters/outbound/postgres/
scheduling_repository.py), RLS-scoped (tasks.md task 7.4)."""

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
        """Inserts a new `appointments` row with `status='scheduled'`.

        Raises `SlotUnavailableError` when the `EXCLUDE USING gist` anti
        double-booking constraint (design.md §4.1) rejects the insert --
        the definitive, race-safe floor for concurrent bookings of the same
        professional/time-slot; `ScheduleAppointment`'s own availability
        check (via `AvailabilityRepositoryPort.reserve_slot`) is a fast-path
        pre-check, not a substitute for this DB-level guarantee (spec
        `appointment-scheduling` -> "Double-booking prevented under
        concurrency")."""
        ...

    async def get_appointment(self, tenant_id: str, appointment_id: str) -> Appointment | None:
        """Tenant-scoped lookup by primary key. Returns `None` when no row
        matches (or the row is invisible under the caller's RLS scope --
        indistinguishable by design, same as every other lookup port in this
        codebase)."""
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
        """Moves the appointment to a new slot/professional and sets
        `status='rescheduled'`. Same `EXCLUDE USING gist`-backed
        `SlotUnavailableError` contract as `create_appointment`."""
        ...

    async def cancel_appointment(self, tenant_id: str, appointment_id: str) -> Appointment:
        """Sets `status='cancelled'` -- never deletes the row (design.md
        §4.1/§6's "baja no borra historia" convention applies here too)."""
        ...
