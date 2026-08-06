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
        """Inserts with status='active'."""
        ...

    async def get_staff_member(self, tenant_id: str, staff_member_id: str) -> StaffMember | None:
        """Tenant-scoped PK lookup; None if missing or RLS-hidden."""
        ...

    async def find_by_professional_id(self, tenant_id: str, professional_id: str) -> StaffMember | None:
        """Lookup by professional_id; None if missing or RLS-hidden."""
        ...

    async def deactivate_staff_member(self, tenant_id: str, staff_member_id: str) -> StaffMember:
        """Sets inactive + deactivated_at; never deletes."""
        ...
