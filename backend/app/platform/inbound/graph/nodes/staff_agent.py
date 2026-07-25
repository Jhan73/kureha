"""`staff_agent` node (design.md §8.2/§8.10, tasks.md task 11.2): plans a
`ProposedAction` for `staff`/`shift` intents (only reachable via
`staff_copilot`, design.md §8.2's own note) against `StaffPlannerPort`
(this batch's seam). Always `risk_level="low"` -- `RiskPolicy` (design.md
§8.4) defines no rule for staff/shift actions; a tenant that wants staff
mutations to require approval configures `action_permissions.
requires_hitl` per-action instead (design.md §8.4 point 1's second HITL
trigger), which is `hitl_approval`'s concern (tasks.md task 11.4, batch
2), not this node's."""

from app.platform.inbound.graph.ports.staff_planner import StaffPlannerPort
from app.platform.inbound.graph.state import KurehaState, ProposedAction
from app.platform.inbound.graph.streaming.status_writer import emit_status


def make_staff_agent_node(planner: StaffPlannerPort):
    async def staff_agent(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        plan = await planner.plan(ctx, intent=state["intent"], message=state["channel_message"])
        emit_status(
            phase="planning_staff_action",
            label="Procesando la solicitud de personal",
            action=plan.action,
            allowed_actions=state.get("allowed_actions"),
        )
        proposed_action = ProposedAction(
            action=plan.action,
            is_mutating=True,
            payload=plan.kwargs,
            summary=plan.summary,
        )
        return {"proposed_action": proposed_action, "risk_level": "low"}

    return staff_agent
