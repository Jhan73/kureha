from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class AvailabilitySlot:
    id: str
    tenant_id: str
    site_id: str
    professional_id: str
    starts_at: datetime
    ends_at: datetime
    status: AvailabilityStatus

    @property
    def is_available(self) -> bool:
        return self.status is AvailabilityStatus.AVAILABLE
