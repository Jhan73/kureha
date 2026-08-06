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
