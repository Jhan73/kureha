"""Task 11.5: `deny_action` node -- curated denial text (no internals
leaked), audits `AuditAction.RBAC_DENIED`."""

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction
from app.platform.inbound.graph.nodes.deny_action import make_deny_action_node
from app.platform.inbound.graph.state import KurehaState, ProposedAction, RequestContext


class _FakeAuditLog:
    def __init__(self) -> None:
        self.entries: list = []

    async def record(self, entry) -> str:
        self.entries.append(entry)
        return "audit-1"


def _state(*, proposed_action: ProposedAction | None) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="reception", site_id="s1", user_id="u1"),
        "channel": "staff_copilot",
        "channel_message": "x",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": None,
        "proposed_action": proposed_action,
        "rbac_ok": False,
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


@pytest.mark.asyncio
async def test_denies_with_curated_text_and_audits_rbac_denied() -> None:
    audit_log = _FakeAuditLog()
    node = make_deny_action_node(audit_log)
    action = ProposedAction(action="staff:register", is_mutating=True, payload={}, summary="secret internal detail")
    state = _state(proposed_action=action)

    result = await node(state)

    assert result["response_text"] == "No tienes permiso para realizar esta accion."
    assert "secret internal detail" not in result["response_text"]
    assert result["audit_ref"] == "audit-1"
    assert audit_log.entries[0].action == AuditAction.RBAC_DENIED
    assert audit_log.entries[0].object_id == "staff:register"


@pytest.mark.asyncio
async def test_handles_missing_proposed_action_defensively() -> None:
    audit_log = _FakeAuditLog()
    node = make_deny_action_node(audit_log)
    state = _state(proposed_action=None)

    result = await node(state)

    assert result["response_text"]
    assert audit_log.entries[0].object_id is None
