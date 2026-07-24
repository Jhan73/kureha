"""`triage` node (design.md §8.2/§8.3, tasks.md task 11.2): the graph's
first classification step -- delegates to `IntentClassifierPort` (this
batch's seam, see `ports/intent_classifier.py`'s module docstring) and sets
`state.intent`. Only reachable when `route_from_start` (tasks.md task 11.6,
not yet built) finds no pending `proposed_action` in the checkpoint -- that
routing decision lives outside this node (it is an `add_conditional_edges`
callback on the compiled graph, design.md §8.2's own note), not enforced
here.

No branching logic beyond "call the classifier, return its verdict" --
downstream routing (`direct_respond` for conversational intents vs
`clinical_scope_validator` for everything else, design.md §8.3) is
`route_by_intent`'s job (task 11.6), not this node's. Matches the house
rule that a node is orchestration only, never business rule logic."""

from app.platform.inbound.graph.ports.intent_classifier import IntentClassifierPort
from app.platform.inbound.graph.state import KurehaState


def make_triage_node(classifier: IntentClassifierPort):
    """Factory, not the node itself -- the returned closure is the plain
    `async def(state) -> dict` LangGraph node (`graph.add_node("triage",
    make_triage_node(real_classifier))`, task 11.6). Factory-wrapping keeps
    the node's own dependency (the classifier) out of `KurehaState` (state
    carries data, not collaborators) while remaining trivially testable
    with a fake classifier -- no real LLM/Postgres needed for unit tests."""

    async def triage(state: KurehaState) -> dict:
        result = await classifier.classify(state["request_ctx"].to_tenant_context(), state["channel_message"])
        return {"intent": result.intent}

    return triage
