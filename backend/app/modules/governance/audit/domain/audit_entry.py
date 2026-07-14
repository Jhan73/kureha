"""`AuditEntry` domain (design.md §4.3): the write-side shape of one
`audit_logs` row. `seq`/`prev_hash`/`row_hash` are computed by the DB's
hash-chain trigger (`audit_hash_chain()`, migration `776b456050fe`) -- they
are never set by application code, so they are not fields on this entity."""

from dataclasses import dataclass, field
from enum import Enum


class AuditActorType(str, Enum):
    """Mirrors `audit_logs.actor_type`'s CHECK constraint exactly."""

    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


class AuditAction(str, Enum):
    """The exact action catalog from design.md §4.3. `AuditLogPort`
    implementations reject anything outside this set by construction --
    `action` is typed as `AuditAction`, not `str`."""

    RBAC_DENIED = "rbac.denied"
    RBAC_GRANTED = "rbac.granted"
    STAFF_REGISTER = "staff.register"
    STAFF_DEACTIVATE = "staff.deactivate"
    SHIFT_CREATE = "shift.create"
    SHIFT_EDIT = "shift.edit"
    CALENDAR_CONNECT = "calendar.connect"
    CALENDAR_SYNC_OK = "calendar.sync_ok"
    CALENDAR_SYNC_FAILED = "calendar.sync_failed"
    CALENDAR_REVOKE = "calendar.revoke"
    APPOINTMENT_CREATE = "appointment.create"
    APPOINTMENT_RESCHEDULE = "appointment.reschedule"
    APPOINTMENT_CANCEL = "appointment.cancel"
    HITL_APPROVE = "hitl.approve"
    HITL_REJECT = "hitl.reject"
    SCOPE_ESCALATE = "scope.escalate"
    CONSENT_BLOCK = "consent.block"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    tenant_id: str
    actor_type: AuditActorType
    action: AuditAction
    object_type: str
    site_id: str | None = None
    actor_id: str | None = None
    object_id: str | None = None
    reason: str | None = None
    approval_id: str | None = None
    payload: dict = field(default_factory=dict)
