from dataclasses import dataclass
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class ReminderPlan:
    appointment_id: str
    summary: str = ""


class ReminderPlannerPort(Protocol):
    async def plan(self, ctx: TenantContext, *, message: str) -> ReminderPlan: ...
