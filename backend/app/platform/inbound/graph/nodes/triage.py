from app.platform.inbound.graph.ports.intent_classifier import IntentClassifierPort
from app.platform.inbound.graph.state import KurehaState


def make_triage_node(classifier: IntentClassifierPort):
    """Factory returning the LangGraph node closure (keeps deps out of state)."""

    async def triage(state: KurehaState) -> dict:
        result = await classifier.classify(state["request_ctx"].to_tenant_context(), state["channel_message"])
        return {"intent": result.intent}

    return triage
