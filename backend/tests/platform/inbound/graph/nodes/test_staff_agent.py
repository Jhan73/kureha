"""Task 11.2: `staff_agent` node -- plans a `ProposedAction` via
`StaffPlannerPort`; always `risk_level="low"` (no `RiskPolicy` rule for
staff/shift, design.md §8.4)."""

import pytest

from app.platform.inbound.graph.nodes.staff_agent import make_staff_agent_node
from app.platform.inbound.graph.ports.staff_planner import StaffPlan
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakePlanner:
    def __init__(self, *, plan: StaffPlan) -> None:
        self._plan = plan

    async def plan(self, ctx, *, intent: str, message: str) -> StaffPlan:
        return self._plan


def _state(*, intent: str) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="reception", site_id="s1", user_id="u1"),
        "channel": "staff_copilot",
        "channel_message": "registra un nuevo staff",
        "intent": intent,
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": ["staff:register", "shift:create"],
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
async def test_staff_agent_produces_a_low_risk_proposed_action_for_staff_intent() -> None:
    plan = StaffPlan(action="staff:register", kwargs={"site_id": "s1", "name": "Ana"}, summary="Register Ana")
    node = make_staff_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="staff"))

    assert result["risk_level"] == "low"
    proposed = result["proposed_action"]
    assert proposed.action == "staff:register"
    assert proposed.is_mutating is True
    assert proposed.payload == plan.kwargs
    assert proposed.summary == plan.summary


@pytest.mark.asyncio
async def test_staff_agent_produces_a_low_risk_proposed_action_for_shift_intent() -> None:
    plan = StaffPlan(action="shift:create", kwargs={"staff_member_id": "s1"}, summary="Create a shift")
    node = make_staff_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="shift"))

    assert result["risk_level"] == "low"
    assert result["proposed_action"].action == "shift:create"
