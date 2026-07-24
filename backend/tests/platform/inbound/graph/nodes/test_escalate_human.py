"""Task 11.5: `escalate_human` node -- audits `AuditAction.SCOPE_ESCALATE`,
sets a curated escalation response, best-effort reason inference."""

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction
from app.platform.inbound.graph.nodes.escalate_human import make_escalate_human_node
from app.platform.inbound.graph.state import ApprovalDecision, KurehaState, ProposedAction, RequestContext


class _FakeAuditLog:
    def __init__(self) -> None:
        self.entries: list = []

    async def record(self, entry) -> str:
        self.entries.append(entry)
        return "audit-1"


def _state(**overrides) -> KurehaState:
    base: KurehaState = {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": "x",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": None,
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
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_escalates_with_curated_text_and_audits_scope_escalate() -> None:
    audit_log = _FakeAuditLog()
    node = make_escalate_human_node(audit_log)
    state = _state(scope_ok=False)

    result = await node(state)

    assert result["response_text"]
    assert result["audit_ref"] == "audit-1"
    assert audit_log.entries[0].action == AuditAction.SCOPE_ESCALATE
    assert audit_log.entries[0].reason == "scope_violation"


@pytest.mark.asyncio
async def test_reason_reflects_consent_violation() -> None:
    audit_log = _FakeAuditLog()
    node = make_escalate_human_node(audit_log)
    state = _state(scope_ok=True, consent_ok=False)

    await node(state)

    assert audit_log.entries[0].reason == "consent_not_current"


@pytest.mark.asyncio
async def test_reason_reflects_hitl_rejection() -> None:
    audit_log = _FakeAuditLog()
    node = make_escalate_human_node(audit_log)
    action = ProposedAction(action="appointment:cancel", is_mutating=True, payload={}, summary="s")
    state = _state(approval=ApprovalDecision(approved=False), proposed_action=action)

    await node(state)

    assert audit_log.entries[0].reason == "hitl_rejected"
    assert audit_log.entries[0].object_id == "appointment:cancel"


@pytest.mark.asyncio
async def test_reason_reflects_unknown_intent_as_fallback() -> None:
    audit_log = _FakeAuditLog()
    node = make_escalate_human_node(audit_log)
    state = _state(intent="unknown")

    await node(state)

    assert audit_log.entries[0].reason == "unknown_intent"
