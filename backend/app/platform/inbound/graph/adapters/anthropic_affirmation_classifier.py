from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationResult
from app.shared_kernel.tenant_context import TenantContext

_SYSTEM_PROMPT = (
    "You are a yes/no affirmation classifier for Tony, a Peruvian clinic operations chat "
    "assistant. Tony has proposed a specific pending action to the user (given below) and is "
    "waiting for the user's reply. Classify the user's message into exactly one category:\n"
    "- affirmed: a clear yes/confirmation of THIS SPECIFIC pending action (e.g. 'si', 'dale', "
    "'confirmo', 'correcto').\n"
    "- declined: a clear no/rejection of THIS SPECIFIC pending action, OR a change of topic/"
    "subject that is not a genuine reply to it.\n"
    "- unclear: the message is not a real reply to this pending action's yes/no question at all "
    "(e.g. it reads like a brand-new, unrelated request).\n"
    "Respond with only the category."
)


class _AffirmationClassification(BaseModel):
    decision: Literal["affirmed", "declined", "unclear"]


class AnthropicAffirmationClassifier:
    """Duck-types `AffirmationClassifierPort`."""

    def __init__(self, llm) -> None:
        self._structured = llm.with_structured_output(_AffirmationClassification)

    async def classify(self, ctx: TenantContext, message: str, *, pending_action_summary: str) -> AffirmationResult:
        try:
            verdict = await self._structured.ainvoke(
                [
                    SystemMessage(content=_SYSTEM_PROMPT),
                    HumanMessage(
                        content=f"Pending action: {pending_action_summary}\nUser reply: {message}"
                    ),
                ]
            )
            decision = verdict.decision
        except Exception:
            decision = "unclear"
        return AffirmationResult(decision=decision)
