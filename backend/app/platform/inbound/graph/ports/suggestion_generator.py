from dataclasses import dataclass, field
from typing import Protocol

from app.modules.governance.rbac.domain.permission import ActionKey
from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class SuggestionCandidate:
    text: str
    action: ActionKey | None = None


@dataclass(frozen=True, slots=True)
class SuggestionContext:
    """Turn facts for suggestion generation.

    `proposed_action_summary` is the just-completed action text (or None).
    """

    intent: str | None
    allowed_actions: list[str] = field(default_factory=list)
    outcome_success: bool | None = None
    proposed_action_summary: str | None = None


class SuggestionGeneratorPort(Protocol):
    async def generate(self, ctx: TenantContext, *, context: SuggestionContext) -> list[SuggestionCandidate]: ...
