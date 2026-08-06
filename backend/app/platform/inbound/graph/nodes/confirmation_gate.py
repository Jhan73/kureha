from app.platform.inbound.graph.ports.affirmation_classifier import AffirmationClassifierPort
from app.platform.inbound.graph.state import KurehaState, ProposedAction

_DECLINE_RESPONSE_TEXT = "Entendido, no realicé la acción. ¿Te ayudo con algo más?"


def _confirmation_prompt(proposed_action: ProposedAction) -> str:
    """Build confirmation prompt from proposed_action.summary."""
    base = proposed_action.summary or proposed_action.action
    return f"{base} ¿Confirmas?"


def make_confirmation_gate_node(affirmation_classifier: AffirmationClassifierPort):
    async def confirmation_gate(state: KurehaState) -> dict:
        # Incoming checkpoint: True if turn N already asked and this is the reply.
        was_awaiting_reply = state.get("confirmation") == "needed"

        proposed_action = state.get("proposed_action")
        if proposed_action is None:
            return {"confirmation": "not_required", "proposed_action": None}

        if state["channel"] == "web_form" or not proposed_action.is_mutating:
            return {"confirmation": "not_required", "proposed_action": proposed_action}

        ctx = state["request_ctx"].to_tenant_context()
        verdict = await affirmation_classifier.classify(
            ctx, state["channel_message"], pending_action_summary=proposed_action.summary
        )

        if verdict.decision == "affirmed":
            return {"confirmation": "affirmed", "proposed_action": proposed_action}

        if verdict.decision == "declined":
            # Clear checkpoint so the next turn is not stuck in confirmation.
            return {
                "confirmation": None,
                "proposed_action": None,
                "response_text": _DECLINE_RESPONSE_TEXT,
            }

        # Unclear reply while awaiting: treat as decline (topic change / ambiguity).
        if was_awaiting_reply:
            return {
                "confirmation": None,
                "proposed_action": None,
                "response_text": _DECLINE_RESPONSE_TEXT,
            }

        # First ask for this proposed action.
        return {
            "confirmation": "needed",
            "proposed_action": proposed_action,
            "response_text": _confirmation_prompt(proposed_action),
        }

    return confirmation_gate
