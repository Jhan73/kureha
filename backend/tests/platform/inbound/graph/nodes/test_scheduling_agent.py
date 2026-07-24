"""Task 11.2: `scheduling_agent` node -- plans a `ProposedAction` via
`SchedulingPlannerPort` and invokes `RiskPolicy` (design.md §8.4 point 1)
to set `state.risk_level`.

Task 11.4 adds `build_scheduling_agent_node` -- the composition-time helper
that resolves `action_permissions.bulk_cancel_threshold` live via
`ActionRiskPort` before constructing the node (below)."""

import pytest

from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskConfig
from app.platform.inbound.graph.nodes.scheduling_agent import (
    build_scheduling_agent_node,
    make_scheduling_agent_node,
)
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlan
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakeActionRisk:
    def __init__(self, *, bulk_cancel_threshold: int) -> None:
        self._config = ActionRiskConfig(requires_hitl=False, bulk_cancel_threshold=bulk_cancel_threshold)
        self.checked_actions: list[str] = []

    async def get(self, action: str) -> ActionRiskConfig:
        self.checked_actions.append(action)
        return self._config


class _FakePlanner:
    def __init__(self, *, plan: SchedulingPlan) -> None:
        self._plan = plan

    async def plan(self, ctx, *, intent: str, message: str) -> SchedulingPlan:
        return self._plan


def _state(*, intent: str) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="patient", patient_id="p1"),
        "channel": "patient_chat",
        "channel_message": "x",
        "intent": intent,
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": ["appointment:create", "appointment:reschedule", "appointment:cancel"],
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
async def test_schedule_intent_produces_a_low_risk_proposed_action() -> None:
    plan = SchedulingPlan(
        action="appointment:create",
        kwargs={"patient_id": "p1", "professional_id": "pro1", "site_id": "s1", "availability_id": "a1"},
        summary="Schedule with Dr. X on Tuesday 10:00",
    )
    node = make_scheduling_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="schedule"))

    assert result["risk_level"] == "low"
    assert result["proposed_action"].action == "appointment:create"
    assert result["proposed_action"].is_mutating is True
    assert result["proposed_action"].payload == plan.kwargs
    assert result["proposed_action"].summary == plan.summary


@pytest.mark.asyncio
async def test_bulk_cancel_over_default_threshold_is_high_risk() -> None:
    plan = SchedulingPlan(
        action="appointment:cancel_bulk",
        kwargs={"appointment_ids": ["a1", "a2", "a3", "a4"]},
        summary="Cancel 4 appointments",
        appointment_ids=["a1", "a2", "a3", "a4"],
    )
    node = make_scheduling_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="cancel"))

    assert result["risk_level"] == "high"


@pytest.mark.asyncio
async def test_cancel_at_default_threshold_is_low_risk() -> None:
    plan = SchedulingPlan(
        action="appointment:cancel_bulk",
        kwargs={"appointment_ids": ["a1", "a2", "a3"]},
        summary="Cancel 3 appointments",
        appointment_ids=["a1", "a2", "a3"],
    )
    node = make_scheduling_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="cancel"))

    assert result["risk_level"] == "low"


@pytest.mark.asyncio
async def test_single_cancel_is_low_risk() -> None:
    plan = SchedulingPlan(
        action="appointment:cancel",
        kwargs={"appointment_id": "a1"},
        summary="Cancel one appointment",
        appointment_ids=["a1"],
    )
    node = make_scheduling_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="cancel"))

    assert result["risk_level"] == "low"


@pytest.mark.asyncio
async def test_reschedule_to_a_different_professional_is_high_risk() -> None:
    plan = SchedulingPlan(
        action="appointment:reschedule",
        kwargs={"appointment_id": "a1", "new_availability_id": "a2"},
        summary="Reschedule with a different professional",
        requested_professional_id="pro1",
        target_professional_id="pro2",
    )
    node = make_scheduling_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="reschedule"))

    assert result["risk_level"] == "high"


@pytest.mark.asyncio
async def test_reschedule_to_the_same_professional_is_low_risk() -> None:
    plan = SchedulingPlan(
        action="appointment:reschedule",
        kwargs={"appointment_id": "a1", "new_availability_id": "a2"},
        summary="Reschedule same professional",
        requested_professional_id="pro1",
        target_professional_id="pro1",
    )
    node = make_scheduling_agent_node(_FakePlanner(plan=plan))

    result = await node(_state(intent="reschedule"))

    assert result["risk_level"] == "low"


@pytest.mark.asyncio
async def test_custom_bulk_cancel_threshold_is_honored() -> None:
    plan = SchedulingPlan(
        action="appointment:cancel_bulk",
        kwargs={"appointment_ids": ["a1", "a2"]},
        summary="Cancel 2 appointments",
        appointment_ids=["a1", "a2"],
    )
    node = make_scheduling_agent_node(_FakePlanner(plan=plan), bulk_cancel_threshold=1)

    result = await node(_state(intent="cancel"))

    assert result["risk_level"] == "high"


@pytest.mark.asyncio
async def test_build_scheduling_agent_node_resolves_the_live_threshold_for_appointment_cancel() -> None:
    action_risk = _FakeActionRisk(bulk_cancel_threshold=1)
    plan = SchedulingPlan(
        action="appointment:cancel_bulk",
        kwargs={"appointment_ids": ["a1", "a2"]},
        summary="Cancel 2 appointments",
        appointment_ids=["a1", "a2"],
    )
    node = await build_scheduling_agent_node(_FakePlanner(plan=plan), action_risk)

    result = await node(_state(intent="cancel"))

    assert result["risk_level"] == "high"  # 2 > live threshold of 1, not the DDL default of 3
    assert action_risk.checked_actions == ["appointment:cancel"]
