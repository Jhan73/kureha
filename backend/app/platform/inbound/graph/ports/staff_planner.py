"""`StaffPlannerPort`: the seam `staff_agent` (tasks.md task 11.2, design.md
§8.2/§8.10) needs to turn `channel_message` into a structured plan for
`staff`/`shift` intents (only reachable via `staff_copilot`, design.md
§8.2's own note). No adapter exists yet -- same seam precedent as
`IntentClassifierPort`/`SchedulingPlannerPort` (this package).

`StaffPlan.kwargs` is shaped 1:1 to match whichever staff use case
(`RegisterStaff`/`DeactivateStaff`/`CreateShift`/`EditShift`,
`modules/staff/application/use_cases/`) `action` selects, mirroring
`SchedulingPlan.kwargs`'s own contract."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class StaffPlan:
    action: ActionKey
    kwargs: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


class StaffPlannerPort(Protocol):
    async def plan(self, ctx: TenantContext, *, intent: str, message: str) -> StaffPlan: ...
