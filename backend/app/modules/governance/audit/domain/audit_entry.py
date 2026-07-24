"""`AuditEntry` domain (design.md §4.3): the write-side shape of one
`audit_logs` row. `seq`/`prev_hash`/`row_hash` are computed by the DB's
hash-chain trigger (`audit_hash_chain()`, migration `776b456050fe`) -- they
are never set by application code, so they are not fields on this entity.

`AUTH_UNMAPPED_IDENTITY` (added Phase 4, tasks.md task 4.3/4.6, flagged not
silently added): design.md §4.3's action catalog paragraph predates the
identity module and has no entry for "an authenticated identity resolved to
no `users` row" -- the `user-authentication` spec's "Authenticated Identity
Maps to Authorization Context" requirement explicitly mandates this be
audited ("the attempt MUST be audited"). Added following the exact
`resource.verb` naming convention every other catalog entry already uses.

`AUTH_INACTIVE_ACTOR`/`AUTH_RATE_LIMITED`/`LLM_BUDGET_EXCEEDED` (added
Phase 5, tasks.md tasks 5.1/5.3, flagged not silently added):
- `auth.inactive_actor`: design.md §4.2's "Gate de estado activo vivo"
  requires the access-control middleware deny+audit a request whose
  `users.status`/`staff_members.status` live lookup is not `active`, even
  though the access token itself is still cryptographically valid and
  unexpired. Distinct from `auth.unmapped_identity` (no `users` row at
  all) -- this is "row found, but inactive".
- `auth.rate_limited`: the `platform-hardening` spec's "Rate Limiting on
  Authentication Endpoints" requirement is explicit that "the throttling
  event MUST be auditable".
- `llm.budget_exceeded`: design.md §19's LLM daily budget cap section is
  explicit -- "El log de consumo se audita en `audit_logs` con
  `action='llm.budget_exceeded'` cuando el cap se alcanza."

`APPOINTMENT_REMINDER_SENT` (added Phase 7, tasks.md task 7.3, flagged not
silently added): the `appointment-scheduling` spec's "Reminders and
Confirmations" requirement is explicit -- "Every delivery attempt MUST be
logged to the audit trail." No existing catalog entry distinguishes a
reminder dispatch attempt from a create/reschedule/cancel mutation.

`CALENDAR_OAUTH_CSRF_ATTEMPT` (added Phase 10, tasks.md task 10.1, flagged
not silently added): design.md §7.3's anti-CSRF `state` check
(`GoogleCalendarAdapter.generate_oauth_state`/`verify_oauth_state`) is a
security control on the OAuth2 callback route -- a mismatched/missing
`state` is a genuine CSRF-attempt signal, distinct from
`CALENDAR_CONNECT`'s existing `status=email_mismatch` payload branch (that
one is an ordinary business outcome of a legitimately-authorized flow; this
one means the callback's CSRF check itself failed, before
`ConnectPatientCalendar` is ever called). Task 10.1's own text requires this
exact catalog entry and requires the callback route to audit rejections
with it.
"""

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
    AUTH_UNMAPPED_IDENTITY = "auth.unmapped_identity"
    AUTH_INACTIVE_ACTOR = "auth.inactive_actor"
    AUTH_RATE_LIMITED = "auth.rate_limited"
    LLM_BUDGET_EXCEEDED = "llm.budget_exceeded"
    APPOINTMENT_REMINDER_SENT = "appointment.reminder_sent"
    CALENDAR_OAUTH_CSRF_ATTEMPT = "calendar.oauth_csrf_attempt"


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
