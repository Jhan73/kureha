"""`resolve_toolset` node (design.md §5.4/§8.2, tasks.md task 11.2): calls
`ListAllowedActions` once per request and stores the full permitted-action
set on `state.allowed_actions`, sorted for deterministic output -- the
copilot's dynamic toolset (a denied action is never offered) AND the input
`rbac_gate`'s in-memory shortcut consumes (design.md §5.6/ADR-16)."""

from app.modules.governance.rbac.application.use_cases.list_allowed_actions import ListAllowedActions
from app.platform.inbound.graph.state import KurehaState
from app.platform.inbound.graph.streaming.status_writer import emit_status


def make_resolve_toolset_node(list_allowed_actions: ListAllowedActions):
    async def resolve_toolset(state: KurehaState) -> dict:
        # `action=None` -- administrative/generic, always emitted (this
        # phase runs BEFORE `allowed_actions` itself is known, so there is
        # nothing yet to scope it against).
        emit_status(phase="resolving_toolset", label="Resolviendo permisos")
        ctx = state["request_ctx"].to_tenant_context()
        actions = await list_allowed_actions.execute(ctx)
        return {"allowed_actions": sorted(actions)}

    return resolve_toolset
