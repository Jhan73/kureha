from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.modules.governance.rbac.adapters.outbound.rbac.action_catalog import ACTION_CATALOG
from app.platform.inbound.graph.ports.direct_response import DirectResponsePlan
from app.shared_kernel.tenant_context import TenantContext

_TONY_IDENTITY = (
    "You are Tony, the administrative operations assistant for a Peruvian medical "
    "clinic. Your role is to help with appointment scheduling and administrative "
    "questions. You recommend and orient administratively, but you NEVER "
    "diagnose, prescribe, or give clinical/medical advice of any kind -- if asked, "
    "politely decline and redirect to what you CAN help with. Tone: friendly, "
    "direct, concise. Always reply in the SAME language the user's message is "
    "written in. Format your reply in Markdown (headings, lists, bold) where it "
    "helps readability, but keep it short -- this is a chat UI, not a document."
)

_ACTION_DESCRIPTIONS: dict[str, str] = {entry.key: entry.description for entry in ACTION_CATALOG}

_INTENT_GUIDANCE: dict[str, str] = {
    "greeting": (
        "The user just greeted you or opened the conversation. Greet them back "
        "warmly, introduce yourself briefly as Tony, and ask how you can help."
    ),
    "small_talk": (
        "The user made casual conversation unrelated to any operational request. "
        "Reply briefly and warmly, then gently steer back to what you can help "
        "with (appointments, administrative questions)."
    ),
    "capability_query": (
        "The user is asking what you can do. Describe your capabilities based "
        "STRICTLY on the list of allowed actions below -- never mention or imply "
        "an action that is not in that list."
    ),
}

_FALLBACK_TEXT = "Lo siento, tuve un problema para responder en este momento. ¿Podrías intentar de nuevo?"


class _DirectResponseText(BaseModel):
    text: str


def _capability_list(allowed_actions: list[str] | None) -> str:
    if not allowed_actions:
        return "(none -- describe only generic self-service orientation, no concrete action)"
    return "\n".join(f"- {action}: {_ACTION_DESCRIPTIONS.get(action, action)}" for action in allowed_actions)


class AnthropicDirectResponse:
    """Duck-types `DirectResponsePort`."""

    def __init__(self, llm) -> None:
        self._structured = llm.with_structured_output(_DirectResponseText)

    async def respond(
        self, ctx: TenantContext, *, intent: str, message: str, allowed_actions: list[str] | None
    ) -> DirectResponsePlan:
        guidance = _INTENT_GUIDANCE.get(intent, _INTENT_GUIDANCE["small_talk"])
        human = (
            f"{guidance}\n\nAllowed actions for this user:\n{_capability_list(allowed_actions)}\n\n"
            f"User's message: {message}"
        )
        try:
            verdict = await self._structured.ainvoke(
                [SystemMessage(content=_TONY_IDENTITY), HumanMessage(content=human)]
            )
        except Exception:
            return DirectResponsePlan(text=_FALLBACK_TEXT)
        return DirectResponsePlan(text=verdict.text)
