"""Write-side shape of one audit_logs row. Hash-chain fields are DB-owned."""

from dataclasses import dataclass, field
from enum import Enum


class AuditActorType(str, Enum):
    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


class AuditAction(str, Enum):
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
    AUTH_UNMAPPED_IDENTITY = "auth.unmapped_identity"
    AUTH_INACTIVE_ACTOR = "auth.inactive_actor"
    AUTH_RATE_LIMITED = "auth.rate_limited"
    LLM_BUDGET_EXCEEDED = "llm.budget_exceeded"
    APPOINTMENT_REMINDER_SENT = "appointment.reminder_sent"
    CALENDAR_OAUTH_CSRF_ATTEMPT = "calendar.oauth_csrf_attempt"
    AUTH_CREDENTIAL_CREATED = "auth.credential_created"
    TENANT_BOOTSTRAP = "tenant.bootstrap"
    OPS_CREDENTIAL_DENIED = "ops.credential_denied"


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
