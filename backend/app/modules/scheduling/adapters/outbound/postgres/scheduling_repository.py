"""`PostgresSchedulingRepository`: `SchedulingRepositoryPort` adapter over
`appointments` (design.md §4.1, migration 3505dc8ce3ad).

Takes an already-open `AsyncConnection` rather than owning an engine, same
pattern every other postgres adapter in this codebase follows. Composition
root (tasks.md task 10.2) MUST construct this against `app.db.runtime_engine`
(`app_runtime`, RLS-enforced) with the request's `SET LOCAL app.*` GUCs
already applied -- never `app.db.engine` for a request-scoped query.

`create_appointment`/`reschedule_appointment` catch `sqlalchemy.exc.
IntegrityError` and translate it to `SlotUnavailableError` -- the ONLY
integrity constraint an authorized, well-formed INSERT/UPDATE against this
table can hit is the `EXCLUDE USING gist` anti double-booking constraint
(design.md §4.1); every FK/CHECK violation would mean the caller passed a
nonexistent id or bad status, which the use-case layer already guards
against via `AvailabilityRepositoryPort`/`get_appointment` lookups before
reaching here."""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.scheduling.domain.appointment import Appointment, AppointmentStatus
from app.modules.scheduling.domain.errors import SlotUnavailableError

_SELECT = (
    "SELECT id, tenant_id, site_id, patient_id, professional_id, availability_id, "
    "starts_at, ends_at, status FROM appointments"
)


class PostgresSchedulingRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

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
        try:
            async with self._conn.begin_nested():
                result = await self._conn.execute(
                    text(
                        "INSERT INTO appointments "
                        "(tenant_id, site_id, patient_id, professional_id, availability_id, starts_at, ends_at) "
                        "VALUES (:tenant_id, :site_id, :patient_id, :professional_id, :availability_id, "
                        ":starts_at, :ends_at) "
                        "RETURNING id, tenant_id, site_id, patient_id, professional_id, availability_id, "
                        "starts_at, ends_at, status"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "site_id": site_id,
                        "patient_id": patient_id,
                        "professional_id": professional_id,
                        "availability_id": availability_id,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                    },
                )
                row = result.one()
        except IntegrityError as exc:
            raise SlotUnavailableError(
                f"professional {professional_id} already has an overlapping active appointment"
            ) from exc
        return self._row_to_appointment(row)

    async def get_appointment(self, tenant_id: str, appointment_id: str) -> Appointment | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": tenant_id, "id": appointment_id},
        )
        row = result.first()
        return self._row_to_appointment(row) if row is not None else None

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
        try:
            async with self._conn.begin_nested():
                result = await self._conn.execute(
                    text(
                        "UPDATE appointments SET professional_id = :professional_id, "
                        "availability_id = :availability_id, starts_at = :starts_at, ends_at = :ends_at, "
                        "status = 'rescheduled', updated_at = now() "
                        "WHERE tenant_id = :tenant_id AND id = :id "
                        "RETURNING id, tenant_id, site_id, patient_id, professional_id, availability_id, "
                        "starts_at, ends_at, status"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "id": appointment_id,
                        "professional_id": professional_id,
                        "availability_id": availability_id,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                    },
                )
                row = result.one()
        except IntegrityError as exc:
            raise SlotUnavailableError(
                f"professional {professional_id} already has an overlapping active appointment"
            ) from exc
        return self._row_to_appointment(row)

    async def cancel_appointment(self, tenant_id: str, appointment_id: str) -> Appointment:
        result = await self._conn.execute(
            text(
                "UPDATE appointments SET status = 'cancelled', updated_at = now() "
                "WHERE tenant_id = :tenant_id AND id = :id "
                "RETURNING id, tenant_id, site_id, patient_id, professional_id, availability_id, "
                "starts_at, ends_at, status"
            ),
            {"tenant_id": tenant_id, "id": appointment_id},
        )
        row = result.one()
        return self._row_to_appointment(row)

    @staticmethod
    def _row_to_appointment(row) -> Appointment:
        return Appointment(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id),
            patient_id=str(row.patient_id),
            professional_id=str(row.professional_id),
            availability_id=str(row.availability_id),
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=AppointmentStatus(row.status),
        )
