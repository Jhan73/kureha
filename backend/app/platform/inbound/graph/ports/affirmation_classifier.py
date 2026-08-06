from dataclasses import dataclass
from typing import Literal, Protocol

from app.shared_kernel.tenant_context import TenantContext

AffirmationDecision = Literal["affirmed", "declined", "unclear"]


@dataclass(frozen=True, slots=True)
class AffirmationResult:
    decision: AffirmationDecision


class AffirmationClassifierPort(Protocol):
    async def classify(self, ctx: TenantContext, message: str, *, pending_action_summary: str) -> AffirmationResult: ...
