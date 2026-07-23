"""`CalendarSyncRecord`/`CalendarSyncStatus`: the read-side shape of one
`calendar_sync` row (design.md §4.4/§7.2, migration 00d985a7bfa5).
`CalendarSyncStatus` mirrors the table's own `CHECK (sync_status IN
('pending','ok','failed'))` exactly -- `CalendarSyncRepositoryPort`
implementations reject anything outside this set by construction, same
convention as `AuditAction` (governance/audit/domain/audit_entry.py)."""

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
