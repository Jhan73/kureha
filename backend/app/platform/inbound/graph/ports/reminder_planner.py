"""`ReminderPlannerPort`: the seam `reminders_agent` (tasks.md task 11.2,
design.md §8.2/§8.10) needs to resolve WHICH appointment a `reminder` intent
refers to. No adapter exists yet -- same seam precedent as
`IntentClassifierPort`/`SchedulingPlannerPort` (this package)."""

from dataclasses import dataclass
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class ReminderPlan:
    appointment_id: str
    summary: str = ""


class ReminderPlannerPort(Protocol):
    async def plan(self, ctx: TenantContext, *, message: str) -> ReminderPlan: ...
