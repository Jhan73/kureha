"""`resolve_toolset` node (design.md §5.4/§8.2, tasks.md task 11.2): calls
`ListAllowedActions` once per request and stores the full permitted-action
set on `state.allowed_actions`, sorted for deterministic output -- the
copilot's dynamic toolset (a denied action is never offered) AND the input
`rbac_gate`'s in-memory shortcut consumes (design.md §5.6/ADR-16)."""

from app.modules.governance.rbac.application.use_cases.list_allowed_actions import ListAllowedActions
from app.platform.inbound.graph.state import KurehaState


def make_resolve_toolset_node(list_allowed_actions: ListAllowedActions):
    async def resolve_toolset(state: KurehaState) -> dict:
        ctx = state["request_ctx"].to_tenant_context()
        actions = await list_allowed_actions.execute(ctx)
        return {"allowed_actions": sorted(actions)}

    return resolve_toolset
