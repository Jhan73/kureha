import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.modules.governance.audit.domain.audit_entry import AuditAction
from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskConfig
from app.platform.inbound.graph.nodes.hitl_approval import make_hitl_approval_node
from app.platform.inbound.graph.state import ApprovalDecision, KurehaState, ProposedAction, RequestContext


class _FakeActionRisk:
    def __init__(self, *, requires_hitl: bool, bulk_cancel_threshold: int = 3) -> None:
        self._config = ActionRiskConfig(requires_hitl=requires_hitl, bulk_cancel_threshold=bulk_cancel_threshold)
        self.checked_actions: list[str] = []

    async def get(self, action: str) -> ActionRiskConfig:
        self.checked_actions.append(action)
        return self._config


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return f"audit-{len(self.recorded)}"


def _state(**overrides) -> KurehaState:
    base: KurehaState = {
        "request_ctx": RequestContext(
            tenant_id="t1", role="reception", site_id="s1", user_id="staff1", patient_id="p1"
        ),
        "channel": "staff_copilot",
        "channel_message": "cancela la cita",
        "intent": "cancel",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": ["appointment:cancel"],
        "proposed_action": ProposedAction(
            action="appointment:cancel",
            is_mutating=True,
            payload={"appointment_id": "a1"},
            summary="Cancelar cita a1",
        ),
        "rbac_ok": True,
        "risk_level": "high",
        "confirmation": "affirmed",
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


def _compiled_graph(node):
    graph = StateGraph(KurehaState)
    graph.add_node("hitl_approval", node)
    graph.add_edge(START, "hitl_approval")
    graph.add_edge("hitl_approval", END)
    return graph.compile(checkpointer=MemorySaver())


@pytest.mark.asyncio
async def test_hitl_approval_pauses_with_the_designed_payload_shape() -> None:
    action_risk = _FakeActionRisk(requires_hitl=False)
    audit_log = _FakeAuditLog()
    node = make_hitl_approval_node(action_risk, audit_log)
    graph = _compiled_graph(node)
    config = {"configurable": {"thread_id": "thread-1"}}

    result = await graph.ainvoke(_state(), config)

    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["action_type"] == "appointment:cancel"
    assert payload["appointment_ids"] == ["a1"]
    assert payload["patient_ref"] == "p1"
    assert payload["requested_by"] == "staff1"
    assert payload["reason"] == "Cancelar cita a1"
    assert audit_log.recorded == []  # not audited until resumed


@pytest.mark.asyncio
async def test_hitl_approval_resumed_with_approval_audits_hitl_approve() -> None:
    action_risk = _FakeActionRisk(requires_hitl=False)
    audit_log = _FakeAuditLog()
    node = make_hitl_approval_node(action_risk, audit_log)
    graph = _compiled_graph(node)
    config = {"configurable": {"thread_id": "thread-2"}}
    await graph.ainvoke(_state(), config)

    result = await graph.ainvoke(Command(resume=ApprovalDecision(approved=True, approved_by="admin1")), config)

    assert result["approval"] == ApprovalDecision(approved=True, approved_by="admin1")
    assert result["audit_ref"] == "audit-1"
    assert len(audit_log.recorded) == 1
    assert audit_log.recorded[0].action == AuditAction.HITL_APPROVE
    assert audit_log.recorded[0].actor_id == "admin1"
    assert audit_log.recorded[0].tenant_id == "t1"


@pytest.mark.asyncio
async def test_hitl_approval_resumed_with_rejection_audits_hitl_reject() -> None:
    action_risk = _FakeActionRisk(requires_hitl=False)
    audit_log = _FakeAuditLog()
    node = make_hitl_approval_node(action_risk, audit_log)
    graph = _compiled_graph(node)
    config = {"configurable": {"thread_id": "thread-3"}}
    await graph.ainvoke(_state(), config)

    result = await graph.ainvoke(
        Command(resume=ApprovalDecision(approved=False, approved_by="admin1", reason="Not safe")), config
    )

    assert result["approval"].approved is False
    assert audit_log.recorded[0].action == AuditAction.HITL_REJECT
    assert audit_log.recorded[0].reason == "Not safe"


@pytest.mark.asyncio
async def test_hitl_approval_reads_requires_hitl_independently_of_risk_level() -> None:
    action_risk = _FakeActionRisk(requires_hitl=True)
    audit_log = _FakeAuditLog()
    node = make_hitl_approval_node(action_risk, audit_log)
    graph = _compiled_graph(node)
    config = {"configurable": {"thread_id": "thread-4"}}

    result = await graph.ainvoke(_state(risk_level="low"), config)

    payload = result["__interrupt__"][0].value
    assert payload["requires_hitl"] is True
    assert action_risk.checked_actions == ["appointment:cancel"]
