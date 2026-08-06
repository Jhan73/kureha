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
