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
