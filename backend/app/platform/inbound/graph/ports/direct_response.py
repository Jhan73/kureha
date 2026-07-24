"""`DirectResponsePort`: the seam `direct_respond` (tasks.md task 11.5,
design.md §8.2/§8.10/§8.11.1) needs to generate a friendly reply for the
three lightweight conversational intents (`greeting`, `capability_query`,
`small_talk`) without running the full consent/RBAC/specialist pipeline. No
adapter exists yet -- same seam precedent as `IntentClassifierPort`/
`SchedulingPlannerPort`/`AffirmationClassifierPort` (this package).

**Deliberately minimal for THIS batch.** design.md §8.11.3 (Tony's full
identity/system-prompt: name, tone, explicit clinical-limit framing) is
tasks.md task 12.5, out of scope here -- this port's contract only carries
what `direct_respond` structurally needs (`intent`, the raw `message`, and
`allowed_actions` so a real future adapter can honor §8.11.1's
`capability_query` rule -- "las capacidades listadas se derivan de
`allowed_actions`... Tony nunca menciona acciones que el usuario no tiene
permiso de ejecutar"). The actual Tony persona/system-prompt content is a
LATER phase's job to inject into whichever adapter eventually implements
this Protocol."""

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
