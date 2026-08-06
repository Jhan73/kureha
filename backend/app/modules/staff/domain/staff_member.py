from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OperationalRole(str, Enum):
    RECEPTION = "reception"
    PROFESSIONAL = "professional"
    ADMIN = "admin"


class StaffStatus(str, Enum):
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
