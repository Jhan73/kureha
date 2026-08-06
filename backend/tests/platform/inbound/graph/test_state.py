from app.modules.governance.rbac.domain.permission import ActionKey
from app.platform.inbound.graph.state import (
    ActionOutcome,
    ApprovalDecision,
    KurehaState,
    ProposedAction,
    RequestContext,
)
from app.shared_kernel.tenant_context import TenantContext


def test_request_context_carries_patient_and_professional_id_unlike_tenant_context() -> None:
    ctx = RequestContext(
        tenant_id="t1",
        role="patient",
        site_id="s1",
        user_id="u1",
        patient_id="p1",
        professional_id=None,
    )

    assert ctx.tenant_id == "t1"
    assert ctx.patient_id == "p1"
    assert ctx.professional_id is None


def test_request_context_converts_to_tenant_context_for_use_case_calls() -> None:
    ctx = RequestContext(tenant_id="t1", role="reception", site_id="s1", user_id="u1", patient_id="p1")

    tenant_ctx = ctx.to_tenant_context()

    assert tenant_ctx == TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")


def test_proposed_action_holds_action_key_payload_and_summary() -> None:
    action: ActionKey = ActionKey("appointment:create")
    proposed = ProposedAction(
        action=action, is_mutating=True, payload={"patient_id": "p1"}, summary="Schedule an appointment"
    )

    assert proposed.action == "appointment:create"
    assert proposed.is_mutating is True
    assert proposed.payload == {"patient_id": "p1"}


def test_kureha_state_accepts_the_full_field_set_from_design_8_1() -> None:
    state: KurehaState = {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": "hola",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": ["appointment:create"],
        "proposed_action": None,
        "rbac_ok": None,
        "risk_level": None,
        "confirmation": None,
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }

    assert state["channel"] == "patient_chat"
    assert state["intent"] == "schedule"


def test_approval_decision_and_action_outcome_construct() -> None:
    approval = ApprovalDecision(approved=True, approved_by="u2", reason="looks fine")
    outcome = ActionOutcome(success=True, result_id="appt-1")

    assert approval.approved is True
    assert outcome.result_id == "appt-1"
