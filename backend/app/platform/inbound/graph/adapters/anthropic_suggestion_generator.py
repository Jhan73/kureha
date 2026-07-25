"""`AnthropicSuggestionGenerator`: the real `SuggestionGeneratorPort` adapter
`respond` consumes (tasks.md task 12.6, design.md §8.10/§8.11.2). Fast/small
tier -- design.md §8.10: "La generacion de sugerencias proactivas es una
tarea de seleccion/ranking sobre `allowed_actions` -- no requiere
razonamiento profundo." Constructor-injected `ChatAnthropic`, built ONLY via
`platform/inbound/graph/adapters/llm.py`'s `build_chat_model("fast")` at the
composition root.

**RBAC-safety is deliberately NOT enforced here.** `respond.py`'s own
docstring is explicit: "the RBAC-safety filter is enforced HERE, in plain
code -- never delegated to `SuggestionGeneratorPort`" -- any candidate whose
`.action` is set but absent from `state.allowed_actions` is dropped
unconditionally by `respond` itself, regardless of what this (untrusted,
LLM-generated) adapter returns. This adapter's `action` field is a plain
`str | None`, NOT a `Literal`-constrained enum like the classifiers built in
batch 1 -- there is no routing/execution decision resting on this value
(unlike `IntentClassifierPort`'s 9 categories, where an invented string
would silently break `_route_by_intent`), so a stricter schema would only
duplicate `ACTION_CATALOG`'s own key list for no additional safety `respond`
doesn't already provide.

**Prompt carries the REAL per-turn context, not a generic one.**
`SuggestionContext.proposed_action_summary` (PR 12 batch 2's own addition to
that dataclass, `ports/suggestion_generator.py`) is the just-completed
action's own `summary` text (e.g. "Agenda una cita el martes 10:00 con la
Dra. Vega") -- design.md §8.11.2's own examples are explicitly contextual to
what JUST happened ("¿Agregar un recordatorio para ESTA cita?"), which a
bare `intent`/`outcome_success` pair cannot express.

**Fails to an empty list on ANY error -- matches `UnwiredSuggestionGenerator`
's own established contract (`adapters/unwired.py`'s own docstring):
suggestions are explicitly OPTIONAL (design.md §8.11.2: "no obligatorias"),
so a generator failure must degrade gracefully, never fail the whole turn
the way a planner/classifier failure legitimately can."""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.platform.inbound.graph.ports.suggestion_generator import SuggestionCandidate, SuggestionContext
from app.shared_kernel.tenant_context import TenantContext

_SYSTEM_PROMPT = (
    "You are the proactive-suggestion generator for Tony, a Peruvian clinic "
    "operations chat assistant. Given the context of what just happened in this "
    "conversation turn, propose UP TO 3 short, relevant follow-up suggestions the "
    "user might want to do next, in the user's own language. Each suggestion may "
    "optionally name a concrete action key from the caller's OWN allowed actions "
    "list below (never a key outside that list) -- leave `action` unset for a "
    "purely orientational suggestion that names no concrete action. Do not "
    "propose anything unrelated to appointment/staff/shift administration."
)


class _SuggestionCandidateOutput(BaseModel):
    text: str
    action: str | None = None


class _SuggestionsOutput(BaseModel):
    suggestions: list[_SuggestionCandidateOutput] = Field(default_factory=list)


def _describe_context(context: SuggestionContext) -> str:
    lines = [f"Intent: {context.intent}", f"Outcome success: {context.outcome_success}"]
    if context.proposed_action_summary:
        lines.append(f"What just happened: {context.proposed_action_summary}")
    allowed = ", ".join(context.allowed_actions) if context.allowed_actions else "(none)"
    lines.append(f"Caller's allowed actions: {allowed}")
    return "\n".join(lines)


class AnthropicSuggestionGenerator:
    """Duck-types `SuggestionGeneratorPort`."""

    def __init__(self, llm) -> None:
        self._structured = llm.with_structured_output(_SuggestionsOutput)

    async def generate(self, ctx: TenantContext, *, context: SuggestionContext) -> list[SuggestionCandidate]:
        try:
            verdict = await self._structured.ainvoke(
                [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=_describe_context(context))]
            )
        except Exception:
            return []
        return [SuggestionCandidate(text=c.text, action=c.action) for c in verdict.suggestions]
