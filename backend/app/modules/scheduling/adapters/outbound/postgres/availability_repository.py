"""`PostgresAvailabilityRepository`: `AvailabilityRepositoryPort` adapter
over `availability` (design.md §4.1, migration 3505dc8ce3ad).

Takes an already-open `AsyncConnection` rather than owning an engine, same
pattern every other postgres adapter in this codebase follows. Composition
root (tasks.md task 10.2) MUST construct this against `app.db.runtime_engine`
(`app_runtime`, RLS-enforced) with the request's `SET LOCAL app.*` GUCs
already applied -- never `app.db.engine` for a request-scoped query."""

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.scheduling.domain.availability import AvailabilitySlot, AvailabilityStatus
from app.modules.scheduling.domain.errors import SlotUnavailableError

_SELECT = "SELECT id, tenant_id, site_id, professional_id, starts_at, ends_at, status FROM availability"


class PostgresAvailabilityRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def find_available_slots(
        self, tenant_id: str, *, site_id: str, professional_id: str, on_date: date
    ) -> list[AvailabilitySlot]:
        result = await self._conn.execute(
            text(
                _SELECT + " WHERE tenant_id = :tenant_id AND site_id = :site_id "
                "AND professional_id = :professional_id AND status = 'available' "
                "AND starts_at::date = :on_date ORDER BY starts_at"
            ),
            {"tenant_id": tenant_id, "site_id": site_id, "professional_id": professional_id, "on_date": on_date},
        )
        return [self._row_to_slot(row) for row in result]

    async def get_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": tenant_id, "id": availability_id},
        )
        row = result.first()
        return self._row_to_slot(row) if row is not None else None

    async def reserve_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        """`UPDATE ... WHERE status = 'available'` makes the check-and-set
        atomic at the DB level -- no SELECT-then-UPDATE race window between
        two concurrent reservations of the same slot."""
        result = await self._conn.execute(
            text(
                "UPDATE availability SET status = 'reserved' "
                "WHERE tenant_id = :tenant_id AND id = :id AND status = 'available' "
                "RETURNING id, tenant_id, site_id, professional_id, starts_at, ends_at, status"
            ),
            {"tenant_id": tenant_id, "id": availability_id},
        )
        row = result.first()
        if row is None:
            raise SlotUnavailableError(f"slot {availability_id} is not available")
        return self._row_to_slot(row)

    async def release_slot(self, tenant_id: str, availability_id: str) -> AvailabilitySlot:
        result = await self._conn.execute(
            text(
                "UPDATE availability SET status = 'available' "
                "WHERE tenant_id = :tenant_id AND id = :id "
                "RETURNING id, tenant_id, site_id, professional_id, starts_at, ends_at, status"
            ),
            {"tenant_id": tenant_id, "id": availability_id},
        )
        row = result.first()
        if row is None:
            raise SlotUnavailableError(f"slot {availability_id} not found")
        return self._row_to_slot(row)

    @staticmethod
    def _row_to_slot(row) -> AvailabilitySlot:
        return AvailabilitySlot(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id),
            professional_id=str(row.professional_id),
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            status=AvailabilityStatus(row.status),
        )
