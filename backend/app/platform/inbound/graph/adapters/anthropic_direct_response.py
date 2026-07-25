"""`AnthropicDirectResponse`: the real `DirectResponsePort` adapter
`direct_respond` consumes (tasks.md task 12.5, design.md §8.10/§8.11.1/
§8.11.3). Fast/small tier -- design.md §8.10: "Generacion de respuesta
conversacional liviana (saludo, capacidades, small talk); texto corto, sin
cadena de razonamiento." Constructor-injected `ChatAnthropic`, built ONLY
via `platform/inbound/graph/adapters/llm.py`'s `build_chat_model("fast")` at
the composition root.

**Closes tasks.md task 12.5, explicitly deferred out of scope by PR 11 batch
3's `direct_respond.py` docstring ("the full Tony identity/system-prompt...
is tasks.md task 12.5, out of scope here").** Builds Tony's real identity
(design.md §8.11.3): name ("Tony"), role (administrative/operational
assistant for appointment/administrative matters), explicit clinical limit
(recommends/orients administratively, NEVER diagnoses or gives clinical
advice -- mirrors `AnthropicScopePolicy`'s own inbound/outbound refusal
categories, this system prompt is the FIRST line of defense, `response_guard`
downstream is the structural backstop, not a substitute for it), tone
(friendly, direct, concise), replies in the user's own language, and formats
in Markdown (§8.8, rendered client-side via `react-markdown`+
`rehype-sanitize`, tasks.md Phase 14).

**`capability_query` derives its capability list from the CALLER'S OWN
`allowed_actions` ONLY (design.md §8.11.1's hard rule) -- reuses
`ACTION_CATALOG`'s existing `key -> description` entries** (governance/
rbac's own single source of truth for what each action key means, tasks.md
task 3.6) rather than duplicating a second description table this module
would have to keep in sync by hand. `allowed_actions=None`/empty tells the
model to describe only generic self-service orientation, never a concrete
action -- proven by this module's own tests (`test_anthropic_direct_
response.py`: not even the catalog's OTHER action keys ever reach the
prompt when the caller has none).

**Falls back to a canned reply on ANY `.ainvoke()` failure -- deliberately
NOT a bare propagate/raise, unlike the scheduling/staff/reminder planners.**
`direct_respond` has no side effect beyond a chat reply (unlike a planner
feeding `persist_and_audit`), so degrading gracefully to a short, safe,
hardcoded reply is a reasonable, deliberate choice here -- mirrors `respond.
py`'s own precedent of hardcoded Spanish fallback templates
(`_GENERIC_FALLBACK_TEXT`/`_GENERIC_SUCCESS_TEXT`) for the same
"never leave the user with a broken turn" reasoning. The fallback text still
passes through `response_guard` downstream like any other `response_text`
(`direct_respond.py`'s own unconditional edge to `response_guard`)."""

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
