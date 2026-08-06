from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.staff.domain.errors import ShiftOverlapError
from app.modules.staff.domain.shift import Shift

_SELECT = "SELECT id, tenant_id, site_id, staff_member_id, starts_at, ends_at FROM shifts"


class PostgresShiftRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_shift(
        self, tenant_id: str, *, site_id: str, staff_member_id: str, starts_at: datetime, ends_at: datetime
    ) -> Shift:
        try:
            async with self._conn.begin_nested():
                result = await self._conn.execute(
                    text(
                        "INSERT INTO shifts (tenant_id, site_id, staff_member_id, starts_at, ends_at) "
                        "VALUES (:tenant_id, :site_id, :staff_member_id, :starts_at, :ends_at) "
                        "RETURNING id, tenant_id, site_id, staff_member_id, starts_at, ends_at"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "site_id": site_id,
                        "staff_member_id": staff_member_id,
                        "starts_at": starts_at,
                        "ends_at": ends_at,
                    },
                )
                row = result.one()
        except IntegrityError as exc:
            raise ShiftOverlapError(f"staff member {staff_member_id} already has an overlapping shift") from exc
        return self._row_to_shift(row)

    async def get_shift(self, tenant_id: str, shift_id: str) -> Shift | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": tenant_id, "id": shift_id},
        )
        row = result.first()
        return self._row_to_shift(row) if row is not None else None

    async def edit_shift(self, tenant_id: str, shift_id: str, *, starts_at: datetime, ends_at: datetime) -> Shift:
        try:
            async with self._conn.begin_nested():
                result = await self._conn.execute(
                    text(
                        "UPDATE shifts SET starts_at = :starts_at, ends_at = :ends_at "
                        "WHERE tenant_id = :tenant_id AND id = :id "
                        "RETURNING id, tenant_id, site_id, staff_member_id, starts_at, ends_at"
                    ),
                    {"tenant_id": tenant_id, "id": shift_id, "starts_at": starts_at, "ends_at": ends_at},
                )
                row = result.one()
        except IntegrityError as exc:
            raise ShiftOverlapError(f"shift {shift_id} would overlap another shift for the same staff member") from exc
        return self._row_to_shift(row)

    @staticmethod
    def _row_to_shift(row) -> Shift:
        return Shift(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id),
            staff_member_id=str(row.staff_member_id),
            starts_at=row.starts_at,
            ends_at=row.ends_at,
        )
