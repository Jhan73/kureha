"""`scheduling_agent` node (design.md §8.2/§8.4 point 1/§8.10, tasks.md
task 11.2): plans a `ProposedAction` for `schedule`/`reschedule`/`cancel`
intents against `SchedulingPlannerPort` (this batch's seam -- no LLM wiring
exists yet, see that port's module docstring) and computes
`state.risk_level` via `RiskPolicy` (scheduling/domain/risk_policy.py)
BEFORE the action reaches `rbac_gate`/`confirmation_gate`/`hitl_approval` --
`risk_policy.py`'s own docstring named this node as its future caller; it
is now that caller.

Does NOT call `ScheduleAppointment`/`RescheduleAppointment`/
`CancelAppointment.execute()` -- planning only. Execution is
`persist_and_audit`'s job (tasks.md task 11.5, batch 2/3), which runs only
after `rbac_gate`, `confirmation_gate` and (if `risk_level=="high"`)
`hitl_approval` have all cleared. `plan.kwargs` is built by the planner to
match those use cases' own `**kwargs` shapes 1:1 (e.g. `schedule`:
`patient_id`/`professional_id`/`site_id`/`availability_id`) so
`persist_and_audit` can call `use_case.execute(ctx, **proposed_action.
payload)` directly without re-parsing anything.

**Bulk-cancel threshold (design.md §8.4 point 1) -- gap closed by tasks.md
task 11.4 (batch 2).** `action_permissions.bulk_cancel_threshold` is a live
Postgres value; `ActionRiskPort`/`ActionRiskReader`
(`governance/rbac/application/ports/driven/action_risk.py`,
`.../adapters/outbound/rbac/action_risk_reader.py`) now read it live. This
node's OWN signature/branching logic is UNCHANGED (`bulk_cancel_threshold:
int` stays a plain constructor parameter, exactly as this docstring
originally anticipated -- "a non-breaking change... an additional
constructor argument, not a rewrite"): `build_scheduling_agent_node` below
is the composition-time helper that resolves the live value and hands it to
`make_scheduling_agent_node`. Whoever eventually builds task 11.6's
`build_graph()`/composition wiring calls `build_scheduling_agent_node`
instead of `make_scheduling_agent_node` directly. Until then this node's
own default (the DDL's documented `3`) remains the fallback for any caller
that still constructs it directly (e.g. this module's own unit tests)."""

from app.modules.governance.rbac.application.ports.driven.action_risk import ActionRiskPort
from app.modules.scheduling.domain.risk_policy import RiskLevel, RiskPolicy
from app.platform.inbound.graph.ports.scheduling_planner import SchedulingPlannerPort
from app.platform.inbound.graph.state import KurehaState, ProposedAction
from app.platform.inbound.graph.streaming.status_writer import emit_status

_DEFAULT_BULK_CANCEL_THRESHOLD = 3

# The only action `RiskPolicy.evaluate_bulk_cancel` concerns: bulk-cancel
# risk only ever applies when `plan.appointment_ids is not None`, which
# `SchedulingPlannerPort`'s own docstring says the planner only ever sets
# for a cancel. Threshold is therefore resolved for THIS key regardless of
# which intent (`schedule`/`reschedule`/`cancel`) a given invocation of the
# node ends up planning.
_BULK_CANCEL_RISK_ACTION = "appointment:cancel"


def make_scheduling_agent_node(
    planner: SchedulingPlannerPort, *, bulk_cancel_threshold: int = _DEFAULT_BULK_CANCEL_THRESHOLD
):
    async def scheduling_agent(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        plan = await planner.plan(ctx, intent=state["intent"], message=state["channel_message"])

        # design.md §8.5's own literal example ("checking_availability" /
        # "Consultando disponibilidad") -- scoped to `state.allowed_actions`
        # (already resolved by `resolve_toolset`, upstream of this node) so
        # a status event never names an action outside the caller's own
        # RBAC grant, even transiently (tasks.md task 12.2, spec
        # `internal-staff-copilot`).
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
    """Composition-time helper (tasks.md task 11.4) closing the gap this
    module's own docstring flagged: reads `action_permissions.
    bulk_cancel_threshold` LIVE for `appointment:cancel` and constructs the
    node with that value instead of the DDL default. `make_scheduling_agent_
    node`'s own signature/branching logic is untouched by this addition --
    this is purely "who constructs it and with what value", exactly the
    composition-time change this module's docstring anticipated. Async
    because resolving the live threshold requires an await (`ActionRiskPort`
    is a live Postgres read) -- callers construct this node once per
    request, same as every other request-scoped port/adapter in this
    codebase (see `ActionRiskReader`'s own docstring)."""
    risk_config = await action_risk.get(_BULK_CANCEL_RISK_ACTION)
    return make_scheduling_agent_node(planner, bulk_cancel_threshold=risk_config.bulk_cancel_threshold)
