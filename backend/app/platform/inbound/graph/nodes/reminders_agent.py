"""`reminders_agent` node (design.md §8.2/§8.10, tasks.md task 11.2): plans
a `ProposedAction` for the `reminder` intent against `ReminderPlannerPort`
(this batch's seam). Always `risk_level="low"` -- `RiskPolicy` (design.md
§8.4) has no rule for reminders, only bulk-cancel and
reschedule-professional-reassignment.

**`is_mutating` judgment call, flagged:** `SendReminder`'s own RBAC action
is `appointment:view` (its module docstring: reused rather than inventing
a dedicated `appointment:reminder` key), which reads like a read-only
action. This node still marks the resulting `ProposedAction.
is_mutating=True` -- sending a reminder has a real-world side effect (a
message delivered to the patient) even though it does not mutate
`appointments`/`availability` rows, and design.md §8.9's confirmation-gate
invariant is framed around `create/update/delete` MUTATIONS
conversationally, not RBAC action-key naming. Flagged here in case a
future review decides a reminder should be `not_required` (`confirmation_
gate` Caso A) instead."""

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
