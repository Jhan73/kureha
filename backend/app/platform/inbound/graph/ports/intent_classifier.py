"""`IntentClassifierPort`: the seam `triage` (tasks.md task 11.2, design.md
§8.2/§8.10) needs to classify `channel_message` into one of `KurehaState`'s
9 `intent` categories. No adapter exists yet: exactly like
`ClinicalScopePolicy` (governance/scope/domain/scope_policy.py), which
design.md §8.7 already names explicitly as a Protocol-only seam with its
LLM-backed implementation deferred to a later phase (tasks.md task 12.3),
`triage`'s own LLM call (design.md §8.10: "Rapido/chico ... Clasificacion de
intent en 9 categorias") has no port ANYWHERE in this codebase before this
batch.

**Flagged decision:** design.md never names this specific port -- only the
`triage` node's classification BEHAVIOR (§8.2/§8.3) and its LLM tier
(§8.10). It is defined here, in `platform/inbound/graph/`, not
`governance/`, because intent routing is graph/orchestration-specific
(which specialist node to route to next) rather than a cross-cutting
security policy every business module must apply -- unlike
`ClinicalScopePolicy`/`AuthorizationPort`, no module outside the graph ever
needs this port. Duck-typed by any future adapter, matching this codebase's
convention of adapters never inheriting their Protocol."""

from dataclasses import dataclass
from typing import Protocol

from app.shared_kernel.tenant_context import TenantContext


@dataclass(frozen=True, slots=True)
class IntentClassificationResult:
    intent: str  # one of KurehaState's 9 `intent` categories (state.py)


class IntentClassifierPort(Protocol):
    async def classify(self, ctx: TenantContext, message: str) -> IntentClassificationResult: ...
