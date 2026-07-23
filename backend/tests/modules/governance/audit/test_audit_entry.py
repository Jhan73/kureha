"""Task 3.3: `AuditEntry` domain (design.md §4.3) -- construction and the
`AuditAction` catalog match the §4.3 list exactly."""

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry

# design.md §4.3's exact action catalog paragraph.
_EXPECTED_ACTIONS = {
    "rbac.denied",
    "rbac.granted",
    "staff.register",
    "staff.deactivate",
    "shift.create",
    "shift.edit",
    "calendar.connect",
    "calendar.sync_ok",
    "calendar.sync_failed",
    "calendar.revoke",
    "appointment.create",
    "appointment.reschedule",
    "appointment.cancel",
    "hitl.approve",
    "hitl.reject",
    "scope.escalate",
    "consent.block",
    # Added by Phase 4 (identity module, tasks.md task 4.3/4.6): design.md
    # §4.3's catalog paragraph predates the identity module and has no entry
    # for "an authenticated identity resolved to no `users` row" -- the
    # `user-authentication` spec's "Authenticated Identity Maps to
    # Authorization Context" requirement explicitly mandates this be audited
    # ("the attempt MUST be audited"). Flagged here, not silently added --
    # see app/modules/governance/audit/domain/audit_entry.py's docstring.
    "auth.unmapped_identity",
    # Added by Phase 5 (access-control middleware, tasks.md task 5.1): the
    # live active-status gate (design.md §4.2 -- "Gate de estado activo
    # vivo") explicitly requires "se deniega y audita" when `users.status`
    # or `staff_members.status` is not 'active', even though an access
    # token is still cryptographically valid. No existing catalog entry
    # covers this distinct cause (`auth.unmapped_identity` is "no users row
    # at all", not "row found but inactive").
    "auth.inactive_actor",
    # Added by Phase 5 (rate-limit middleware, tasks.md task 5.3): the
    # `platform-hardening` spec's "Rate Limiting on Authentication
    # Endpoints" requires the throttling event itself be auditable
    # ("the throttling event MUST be auditable").
    "auth.rate_limited",
    # Added by Phase 5 (rate-limit middleware, tasks.md task 5.3): design.md
    # §19's LLM daily budget cap is explicit -- "El log de consumo se
    # audita en audit_logs con action='llm.budget_exceeded' cuando el cap
    # se alcanza."
    "llm.budget_exceeded",
    # Added by Phase 7 (scheduling module, tasks.md task 7.3): the
    # `appointment-scheduling` spec's "Reminders and Confirmations"
    # requirement is explicit -- "Every delivery attempt MUST be logged to
    # the audit trail." No existing catalog entry covers a reminder dispatch
    # attempt (as opposed to a create/reschedule/cancel mutation), so this is
    # a new entry following the exact `resource.verb` convention every other
    # one already uses -- flagged here, not silently added.
    "appointment.reminder_sent",
}


def test_audit_action_catalog_matches_design_doc_4_3() -> None:
    assert {action.value for action in AuditAction} == _EXPECTED_ACTIONS


def test_audit_actor_type_matches_the_db_check_constraint() -> None:
    assert {actor.value for actor in AuditActorType} == {"agent", "user", "system"}


def test_audit_entry_defaults_payload_to_empty_dict() -> None:
    entry = AuditEntry(
        tenant_id="t1",
        actor_type=AuditActorType.USER,
        action=AuditAction.RBAC_DENIED,
        object_type="action_permission",
    )

    assert entry.payload == {}
    assert entry.site_id is None
    assert entry.actor_id is None
    assert entry.object_id is None


def test_audit_entry_holds_every_field() -> None:
    entry = AuditEntry(
        tenant_id="t1",
        site_id="s1",
        actor_id="u1",
        actor_type=AuditActorType.SYSTEM,
        action=AuditAction.CALENDAR_SYNC_FAILED,
        object_type="appointment",
        object_id="a1",
        reason="google api timeout",
        approval_id=None,
        payload={"attempts": 3},
    )

    assert entry.tenant_id == "t1"
    assert entry.site_id == "s1"
    assert entry.actor_id == "u1"
    assert entry.actor_type == AuditActorType.SYSTEM
    assert entry.action == AuditAction.CALENDAR_SYNC_FAILED
    assert entry.object_type == "appointment"
    assert entry.object_id == "a1"
    assert entry.reason == "google api timeout"
    assert entry.payload == {"attempts": 3}
