from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CalendarSyncStatus(str, Enum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CalendarSyncRecord:
    id: str
    tenant_id: str
    site_id: str
    appointment_id: str
    idempotency_key: str
    status: CalendarSyncStatus
    attempts: int
    updated_at: datetime
    google_event_id: str | None = None
    last_error: str | None = None
