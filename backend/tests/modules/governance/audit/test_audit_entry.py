from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry

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
    "auth.unmapped_identity",
    "auth.inactive_actor",
    "auth.rate_limited",
    "llm.budget_exceeded",
    "appointment.reminder_sent",
    "calendar.oauth_csrf_attempt",
    "auth.credential_created",
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
