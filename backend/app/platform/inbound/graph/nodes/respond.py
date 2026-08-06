from app.platform.inbound.graph.ports.suggestion_generator import SuggestionContext, SuggestionGeneratorPort
from app.platform.inbound.graph.state import KurehaState

_MAX_SUGGESTIONS = 3
_SUGGESTIONS_HEADER = "¿También te puedo ayudar con?"
_GENERIC_SUCCESS_TEXT = "Listo, la acción se completó con éxito."
_GENERIC_FALLBACK_TEXT = "Tu solicitud fue procesada."

_OPERATIONAL_INTENTS = frozenset({"schedule", "reschedule", "cancel"})
_LIGHT_INTENTS = frozenset({"greeting", "capability_query"})


def _compose_response_text(state: KurehaState) -> str:
    outcome = state.get("outcome")
    if outcome is None or not outcome.success:
        return _GENERIC_FALLBACK_TEXT

    proposed_action = state.get("proposed_action")
    base = f"Listo, {proposed_action.summary}" if proposed_action is not None and proposed_action.summary else _GENERIC_SUCCESS_TEXT

    if state.get("calendar_sync_status") == "failed":
        base += " No pudimos sincronizar tu Google Calendar, pero la cita quedó registrada."

    return base


def _suggestions_justified(state: KurehaState) -> bool:
    intent = state.get("intent")
    if intent in _LIGHT_INTENTS or intent == "unknown":
        return True
    if intent in _OPERATIONAL_INTENTS:
        outcome = state.get("outcome")
        return outcome is not None and outcome.success
    return False


def _format_suggestions(response_text: str, suggestions: list[str]) -> str:
    bullet_list = "\n".join(f"- {text}" for text in suggestions)
    return f"{response_text}\n\n{_SUGGESTIONS_HEADER}\n{bullet_list}"


def make_respond_node(suggestion_generator: SuggestionGeneratorPort):
    async def respond(state: KurehaState) -> dict:
        response_text = state.get("response_text")
        if not response_text:
            response_text = _compose_response_text(state)

        suggestions: list[str] | None = None
        if _suggestions_justified(state):
            ctx = state["request_ctx"].to_tenant_context()
            outcome = state.get("outcome")
            allowed_actions = state.get("allowed_actions") or []
            proposed_action = state.get("proposed_action")
            candidates = await suggestion_generator.generate(
                ctx,
                context=SuggestionContext(
                    intent=state.get("intent"),
                    allowed_actions=list(allowed_actions),
                    outcome_success=outcome.success if outcome is not None else None,
                    proposed_action_summary=proposed_action.summary if proposed_action is not None else None,
                ),
            )
            allowed = set(allowed_actions)
            safe_texts = [c.text for c in candidates if c.action is None or c.action in allowed]
            suggestions = safe_texts[:_MAX_SUGGESTIONS] or None

        if suggestions:
            response_text = _format_suggestions(response_text, suggestions)

        result: dict = {"response_text": response_text, "suggestions": suggestions}
        if state.get("confirmation") == "needed":
            # Keep proposed_action while awaiting confirmation reply.
            result["proposed_action"] = state.get("proposed_action")
        else:
            # Clear so the next turn is not misrouted into confirmation_gate.
            result["proposed_action"] = None
        return result

    return respond
