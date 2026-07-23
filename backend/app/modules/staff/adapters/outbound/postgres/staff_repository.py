"""`PostgresStaffRepository`: `StaffRepositoryPort` adapter over
`staff_members` (design.md §4.4, migration d0e2489a94b8).

Takes an already-open `AsyncConnection` rather than owning an engine, same
pattern every other postgres adapter in this codebase follows. Composition
root (tasks.md task 10.2) MUST construct this against `app.db.runtime_engine`
(`app_runtime`, RLS-enforced) with the request's `SET LOCAL app.*` GUCs
already applied -- never `app.db.engine` for a request-scoped query.

No delete method by construction (mirrors `PostgresSchedulingRepository.
cancel_appointment`'s "never deletes" precedent) -- `deactivate_staff_member`
is the only supported terminal state transition, matching design.md §6's
"baja no borra historia"."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.modules.staff.domain.staff_member import OperationalRole, StaffMember, StaffStatus

_SELECT = (
    "SELECT id, tenant_id, site_id, user_id, professional_id, name, operational_role, status, "
    "activated_at, deactivated_at FROM staff_members"
)


class PostgresStaffRepository:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_staff_member(
        self,
        tenant_id: str,
        *,
        site_id: str,
        name: str,
        operational_role: OperationalRole,
        user_id: str | None = None,
        professional_id: str | None = None,
    ) -> StaffMember:
        result = await self._conn.execute(
            text(
                "INSERT INTO staff_members (tenant_id, site_id, user_id, professional_id, name, operational_role) "
                "VALUES (:tenant_id, :site_id, :user_id, :professional_id, :name, :operational_role) "
                "RETURNING id, tenant_id, site_id, user_id, professional_id, name, operational_role, status, "
                "activated_at, deactivated_at"
            ),
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "user_id": user_id,
                "professional_id": professional_id,
                "name": name,
                "operational_role": operational_role.value,
            },
        )
        row = result.one()
        return self._row_to_staff_member(row)

    async def get_staff_member(self, tenant_id: str, staff_member_id: str) -> StaffMember | None:
        result = await self._conn.execute(
            text(_SELECT + " WHERE tenant_id = :tenant_id AND id = :id"),
            {"tenant_id": tenant_id, "id": staff_member_id},
        )
        row = result.first()
        return self._row_to_staff_member(row) if row is not None else None

    async def deactivate_staff_member(self, tenant_id: str, staff_member_id: str) -> StaffMember:
        result = await self._conn.execute(
            text(
                "UPDATE staff_members SET status = 'inactive', deactivated_at = now() "
                "WHERE tenant_id = :tenant_id AND id = :id "
                "RETURNING id, tenant_id, site_id, user_id, professional_id, name, operational_role, status, "
                "activated_at, deactivated_at"
            ),
            {"tenant_id": tenant_id, "id": staff_member_id},
        )
        row = result.one()
        return self._row_to_staff_member(row)

    @staticmethod
    def _row_to_staff_member(row) -> StaffMember:
        return StaffMember(
            id=str(row.id),
            tenant_id=str(row.tenant_id),
            site_id=str(row.site_id),
            user_id=str(row.user_id) if row.user_id is not None else None,
            professional_id=str(row.professional_id) if row.professional_id is not None else None,
            name=row.name,
            operational_role=OperationalRole(row.operational_role),
            status=StaffStatus(row.status),
            activated_at=row.activated_at,
            deactivated_at=row.deactivated_at,
        )
