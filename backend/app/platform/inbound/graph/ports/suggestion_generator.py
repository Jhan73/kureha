"""`SuggestionGeneratorPort`: the seam `respond` (tasks.md task 11.5,
design.md §8.2/§8.10/§8.11.2) needs for the TEXT of up to 3 proactive
suggestions. No adapter exists yet -- same seam precedent as every other
LLM-shaped port in this package.

**RBAC-safety is deliberately NOT this port's job.** design.md §8.11.2's
"Tony nunca sugiere una accion que el usuario no tiene permiso de ejecutar"
is a hard security invariant, not a language-generation concern -- `respond`
itself (plain code, not this seam) drops any `SuggestionCandidate` whose
`action` is set but absent from `state.allowed_actions`, defensively,
regardless of what this port returns. A candidate's `action` is `None` for a
purely orientational suggestion that names no concrete RBAC-gated action
(e.g. "Puedo ayudarte a agendar una cita, reprogramar, o cancelar" for an
`unknown` intent) -- `respond` never filters those on `allowed_actions`
since there is nothing to check."""

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
    """What `respond` (tasks.md task 11.5) already knows about the turn,
    handed to the generator as-is -- no re-derivation inside the port."""

    intent: str | None
    allowed_actions: list[str] = field(default_factory=list)
    outcome_success: bool | None = None


class SuggestionGeneratorPort(Protocol):
    async def generate(self, ctx: TenantContext, *, context: SuggestionContext) -> list[SuggestionCandidate]: ...
