"""`AffirmationClassifierPort`: the seam `confirmation_gate` (tasks.md task
11.3, design.md §8.9 Caso C) needs to judge whether a channel message
affirms, declines, or is unrelated to ("unclear") a pending
`proposed_action`. No adapter exists yet -- same seam precedent as
`IntentClassifierPort`/`SchedulingPlannerPort` (this package) and
`ClinicalScopePolicy`. design.md §8.10 names `confirmation_gate` as
LLM-backed ("Rapido/chico ... Clasificacion de afirmacion/rechazo (yes/no
semantico) + generacion de texto corto de confirmacion").

**Three-way, not boolean -- see `nodes/confirmation_gate.py`'s module
docstring for the full rationale.** A plain `affirmed: bool` cannot express
design.md §8.9's asymmetry between Caso B (turn N's original request,
never a reply to anything -> `confirmation_gate` must emit `"needed"`) and
Caso C (turn N+1's reply to an already-asked prompt, where anything short
of a clear yes -> `"declined"`). `"unclear"` is what a real classifier
should return for a message that is not a reply to any yes/no question at
all (Caso B's original operational request); `"declined"` is reserved for
an explicit "no"/topic-change/silence AFTER a confirmation prompt was
already asked (Caso C) -- distinguishing the two is a genuine
conversational-context judgment call for the real (future) LLM-backed
adapter, not something this Protocol-only seam encodes."""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.shared_kernel.tenant_context import TenantContext

AffirmationDecision = Literal["affirmed", "declined", "unclear"]


@dataclass(frozen=True, slots=True)
class AffirmationResult:
    decision: AffirmationDecision


class AffirmationClassifierPort(Protocol):
    async def classify(self, ctx: TenantContext, message: str, *, pending_action_summary: str) -> AffirmationResult: ...
