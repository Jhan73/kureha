from dataclasses import dataclass
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class DirectResponsePlan:
    text: str


class DirectResponsePort(Protocol):
    async def respond(
        self, ctx: TenantContext, *, intent: str, message: str, allowed_actions: list[str] | None
    ) -> DirectResponsePlan: ...
