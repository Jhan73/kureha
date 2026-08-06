import pytest

from app.platform.inbound.graph.nodes.reminders_agent import make_reminders_agent_node
from app.platform.inbound.graph.ports.reminder_planner import ReminderPlan
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakePlanner:
    def __init__(self, *, plan: ReminderPlan) -> None:
        self._plan = plan

    async def plan(self, ctx, *, message: str) -> ReminderPlan:
        return self._plan


def _state() -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": "recuerdame mi cita",
        "intent": "reminder",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": ["appointment:view"],
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


@pytest.mark.asyncio
async def test_reminders_agent_produces_a_low_risk_proposed_action() -> None:
    plan = ReminderPlan(appointment_id="a1", summary="Remind about tomorrow's appointment")
    node = make_reminders_agent_node(_FakePlanner(plan=plan))

    result = await node(_state())

    assert result["risk_level"] == "low"
    proposed = result["proposed_action"]
    assert proposed.action == "appointment:view"
    assert proposed.is_mutating is True
    assert proposed.payload == {"appointment_id": "a1"}
    assert proposed.summary == plan.summary


@pytest.mark.asyncio
async def test_emits_a_status_event_scoped_to_appointment_view(monkeypatch) -> None:
    import app.platform.inbound.graph.nodes.reminders_agent as module

    calls: list[dict] = []
    monkeypatch.setattr(module, "emit_status", lambda **kw: calls.append(kw))
    plan = ReminderPlan(appointment_id="a1", summary="Remind about tomorrow's appointment")
    node = make_reminders_agent_node(_FakePlanner(plan=plan))

    await node(_state())

    assert len(calls) == 1
    assert calls[0]["action"] == "appointment:view"
    assert calls[0]["allowed_actions"] == ["appointment:view"]
