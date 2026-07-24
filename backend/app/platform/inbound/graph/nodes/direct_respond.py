"""`direct_respond` node (design.md §8.2/§8.3/§8.10/§8.11.1, tasks.md task
11.5): the fast lane for `greeting`/`capability_query`/`small_talk` intents
-- `triage -> direct_respond -> response_guard -> respond -> END`, never
touching consent/RBAC/specialists. Delegates to `DirectResponsePort` (this
batch's new seam, `ports/direct_response.py` -- see that module's own
docstring for why it is deliberately minimal this batch) and sets
`state.response_text`.

**Basic/structural only -- the full Tony identity/system-prompt (design.md
§8.11.3) is tasks.md task 12.5, out of scope here.** This node's own
responsibility ends at "call the seam, take its text" -- exactly the same
shape as every other specialist node in this package (`triage`,
`scheduling_agent`, ...): a node is orchestration only, never business/
generation logic itself."""

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
