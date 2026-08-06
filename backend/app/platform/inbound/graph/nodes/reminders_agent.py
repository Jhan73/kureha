from app.platform.inbound.graph.ports.reminder_planner import ReminderPlannerPort
from app.platform.inbound.graph.state import KurehaState, ProposedAction
from app.platform.inbound.graph.streaming.status_writer import emit_status

_ACTION = "appointment:view"


def make_reminders_agent_node(planner: ReminderPlannerPort):
    async def reminders_agent(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        plan = await planner.plan(ctx, message=state["channel_message"])
        emit_status(
            phase="planning_reminder",
            label="Preparando el recordatorio",
            action=_ACTION,
            allowed_actions=state.get("allowed_actions"),
        )
        proposed_action = ProposedAction(
            action="appointment:view",
            is_mutating=True,
            payload={"appointment_id": plan.appointment_id},
            summary=plan.summary,
        )
        return {"proposed_action": proposed_action, "risk_level": "low"}

    return reminders_agent
