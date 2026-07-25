"""`AnthropicIntentClassifier`: the real `IntentClassifierPort` adapter
`triage` consumes (tasks.md task 12.2's adapter half, design.md §8.2/§8.10).
Fast/small tier -- design.md §8.10: "Clasificacion de intent en 9
categorias: latencia critica (primer nodo)". Constructor-injected
`ChatAnthropic`, built ONLY via `platform/inbound/graph/adapters/llm.py`'s
`build_chat_model("fast")` at the composition root -- never inline here.

Lives flat in `graph/adapters/` (not a provider-named subfolder) --
`IntentClassifierPort` is a graph-local seam (see that port's own module
docstring: "no module outside the graph ever needs this port"), matching
`adapters/unwired.py`'s existing flat-file convention for every OTHER
graph-local seam's placeholder in this same package, rather than
`governance/scope`'s cross-cutting-policy convention of a provider
subfolder.

**Structured output constrained to the EXACT 9 `KurehaState.intent` Literal
values** -- an intent classifier that could return a typo'd or invented
string would silently break every downstream `_route_by_intent`/
`_route_from_triage` conditional edge in `build_graph.py` (this task's own
explicit warning). `_IntentClassification.intent` is a `Literal` of those 9
strings, so any OTHER value can only ever surface as a structured-output
validation failure -- caught below, never silently accepted.

**Fails closed to `"unknown"` on ANY error** (network failure, refusal,
validation failure of a malformed response) -- `build_graph.py`'s own
`_route_by_intent` already routes `"unknown"` to `escalate_human`, so a
classification failure never silently reaches a specialist agent it has no
real intent basis for."""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.platform.inbound.graph.ports.intent_classifier import IntentClassificationResult
from app.shared_kernel.tenant_context import TenantContext

_IntentLiteral = Literal[
    "schedule",
    "reschedule",
    "cancel",
    "reminder",
    "staff",
    "shift",
    "greeting",
    "capability_query",
    "small_talk",
    "unknown",
]

_SYSTEM_PROMPT = (
    "You are the intent router for Tony, a Peruvian clinic operations chat assistant. "
    "Classify the user's message into exactly ONE of these 9 categories:\n"
    "- schedule: wants to book a new appointment.\n"
    "- reschedule: wants to change the date/time of an existing appointment.\n"
    "- cancel: wants to cancel an existing appointment.\n"
    "- reminder: wants a reminder sent about an appointment.\n"
    "- staff: a staff-management request (register/deactivate a staff member) -- only valid "
    "for staff callers.\n"
    "- shift: a shift-management request (create/edit a work shift) -- only valid for staff "
    "callers.\n"
    "- greeting: a greeting/hello with no other operational content.\n"
    "- capability_query: asks what the assistant can do.\n"
    "- small_talk: casual conversation unrelated to any operational request.\n"
    "- unknown: none of the above apply, or the message is ambiguous.\n"
    "Respond with only the category."
)


class _IntentClassification(BaseModel):
    intent: _IntentLiteral


class AnthropicIntentClassifier:
    """Duck-types `IntentClassifierPort`."""

    def __init__(self, llm) -> None:
        self._structured = llm.with_structured_output(_IntentClassification)

    async def classify(self, ctx: TenantContext, message: str) -> IntentClassificationResult:
        try:
            verdict = await self._structured.ainvoke(
                [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=message)]
            )
            intent = verdict.intent
        except Exception:
            intent = "unknown"
        return IntentClassificationResult(intent=intent)
