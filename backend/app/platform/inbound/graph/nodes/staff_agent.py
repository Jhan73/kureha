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
