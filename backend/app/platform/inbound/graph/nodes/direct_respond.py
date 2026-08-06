from app.platform.inbound.graph.ports.direct_response import DirectResponsePort
from app.platform.inbound.graph.state import KurehaState


def make_direct_respond_node(direct_response: DirectResponsePort):
    async def direct_respond(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        plan = await direct_response.respond(
            ctx,
            intent=state["intent"],
            message=state["channel_message"],
            allowed_actions=state.get("allowed_actions"),
        )
        return {"response_text": plan.text}

    return direct_respond
