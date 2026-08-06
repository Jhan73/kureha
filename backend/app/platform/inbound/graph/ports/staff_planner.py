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
