from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Shift:
    id: str
    tenant_id: str
    site_id: str
    staff_member_id: str
    starts_at: datetime
    ends_at: datetime
