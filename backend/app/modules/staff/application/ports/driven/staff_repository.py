"""`StaffRepositoryPort` (design.md §4.4): `staff_members` access for the
staff module's use cases. Implemented in MVP by `PostgresStaffRepository`
(adapters/outbound/postgres/staff_repository.py), RLS-scoped (tasks.md task
8.3).

Deliberately has NO delete method -- design.md §6's "baja no borra historia"
(deactivation never erases history) is enforced structurally by only
offering `deactivate_staff_member` (a status flip), the same precedent
`SchedulingRepositoryPort.cancel_appointment`'s docstring documents."""

from typing import Protocol

from app.modules.staff.domain.staff_member import OperationalRole, StaffMember


class StaffRepositoryPort(Protocol):
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
        """Inserts a new `staff_members` row with `status='active'`."""
        ...

    async def get_staff_member(self, tenant_id: str, staff_member_id: str) -> StaffMember | None:
        """Tenant-scoped lookup by primary key. Returns `None` when no row
        matches (or the row is invisible under the caller's RLS scope --
        indistinguishable by design, same as every other lookup port in this
        codebase)."""
        ...

    async def deactivate_staff_member(self, tenant_id: str, staff_member_id: str) -> StaffMember:
        """Sets `status='inactive'` and `deactivated_at=now()` -- never
        deletes the row (design.md §6's "baja no borra historia")."""
        ...
