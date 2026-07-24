"""`SchedulingPlannerPort`: the seam `scheduling_agent` (tasks.md task 11.2,
design.md §8.2/§8.4 point 1/§8.10) needs to turn `channel_message` into a
structured plan for `schedule`/`reschedule`/`cancel` intents. No adapter
exists yet -- same seam precedent as `IntentClassifierPort` (this
package's `intent_classifier.py`) and `ClinicalScopePolicy`.

`SchedulingPlan.kwargs` is shaped 1:1 to match whichever scheduling use
case (`ScheduleAppointment`/`RescheduleAppointment`/`CancelAppointment`,
`modules/scheduling/application/use_cases/`) `action` selects, so
`persist_and_audit` (tasks.md task 11.5, batch 2/3) can call
`use_case.execute(ctx, **plan.kwargs)` directly.

`appointment_ids`/`requested_professional_id`/`target_professional_id` are
NOT part of `kwargs` -- they exist solely to feed `scheduling_agent`'s
`RiskPolicy.evaluate_bulk_cancel`/`evaluate_reschedule` calls (design.md
§8.4 point 1, `scheduling/domain/risk_policy.py`). `appointment_ids` is set
by the planner for ANY cancel (a single-element list for a plain cancel, a
longer list for a bulk cancel) -- `scheduling_agent` always runs the bulk
check against whatever count the planner determined; a normal single cancel
is simply never `> threshold`."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class SchedulingPlan:
    action: ActionKey
    kwargs: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    appointment_ids: list[str] | None = None
    requested_professional_id: str | None = None
    target_professional_id: str | None = None


class SchedulingPlannerPort(Protocol):
    async def plan(self, ctx: TenantContext, *, intent: str, message: str) -> SchedulingPlan: ...
