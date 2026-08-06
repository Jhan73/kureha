from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskPort
from app.modules.scheduling.domain.risk_policy import RiskLevel, RiskPolicy
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlannerPort
from app.platform.inbound.graph.state import KurehaState, ProposedAction
from app.platform.inbound.graph.streaming.status_writer import emit_status

_DEFAULT_BULK_CANCEL_THRESHOLD = 3

# Bulk-cancel risk only applies when plan.appointment_ids is set (cancel).
_BULK_CANCEL_RISK_ACTION = "appointment:cancel"


def make_scheduling_agent_node(
    planner: SchedulingPlannerPort, *, bulk_cancel_threshold: int = _DEFAULT_BULK_CANCEL_THRESHOLD
):
    async def scheduling_agent(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        plan = await planner.plan(ctx, intent=state["intent"], message=state["channel_message"])

        # Status action must stay within allowed_actions (RBAC).
        emit_status(
            phase="checking_availability",
            label="Consultando disponibilidad",
            action=plan.action,
            allowed_actions=state.get("allowed_actions"),
        )

        if plan.appointment_ids is not None:
            risk = RiskPolicy.evaluate_bulk_cancel(len(plan.appointment_ids), threshold=bulk_cancel_threshold)
        elif plan.requested_professional_id is not None and plan.target_professional_id is not None:
            risk = RiskPolicy.evaluate_reschedule(
                requested_professional_id=plan.requested_professional_id,
                target_professional_id=plan.target_professional_id,
            )
        else:
            risk = RiskLevel.LOW

        proposed_action = ProposedAction(
            action=plan.action,
            is_mutating=True,  # every schedule/reschedule/cancel outcome mutates appointment state
            payload=plan.kwargs,
            summary=plan.summary,
        )
        return {"proposed_action": proposed_action, "risk_level": risk.value}

    return scheduling_agent


async def build_scheduling_agent_node(planner: SchedulingPlannerPort, action_risk: ActionRiskPort):
    """Load live bulk_cancel_threshold for appointment:cancel, then build the node."""
    risk_config = await action_risk.get(_BULK_CANCEL_RISK_ACTION)
    return make_scheduling_agent_node(planner, bulk_cancel_threshold=risk_config.bulk_cancel_threshold)
