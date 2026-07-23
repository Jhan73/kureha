"""`StaffMember` domain (design.md §4.4/§6's `staff_members` table shape).
Pure value object -- operational-status invariant only, no IO. Operational
registry ONLY (no HR fields: no payroll/contracts/performance-evaluation --
spec `staff-registry` -> "Out-of-HR-Scope Boundary"). The actual "deactivate
never deletes" guarantee (design.md §6) lives at the port/adapter layer:
`StaffRepositoryPort` deliberately exposes no delete method, only
`deactivate_staff_member` (a status flip), mirroring
`SchedulingRepositoryPort.cancel_appointment`'s "never deletes the row"
precedent."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OperationalRole(str, Enum):
    """Mirrors `staff_members.operational_role`'s CHECK constraint exactly
    (design.md §4.4)."""

    RECEPTION = "reception"
    PROFESSIONAL = "professional"
    ADMIN = "admin"


class StaffStatus(str, Enum):
    """Mirrors `staff_members.status`'s CHECK constraint exactly (design.md
    §4.4)."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class StaffMember:
    id: str
    tenant_id: str
    site_id: str
    name: str
    operational_role: OperationalRole
    status: StaffStatus
    activated_at: datetime
    user_id: str | None = None
    professional_id: str | None = None
    deactivated_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status is StaffStatus.ACTIVE
