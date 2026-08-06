from dataclasses import dataclass
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class IntentClassificationResult:
    intent: str  # one of KurehaState's 9 `intent` categories (state.py)


class IntentClassifierPort(Protocol):
    async def classify(self, ctx: TenantContext, message: str) -> IntentClassificationResult: ...
