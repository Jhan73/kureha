from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.platform.inbound.graph.state import KurehaState


def make_rbac_gate_node(authorize_action: AuthorizeAction):
    async def rbac_gate(state: KurehaState) -> dict:
        proposed_action = state.get("proposed_action")
        if proposed_action is None:
            return {"rbac_ok": False}

        allowed_actions = state.get("allowed_actions")
        if allowed_actions is not None and proposed_action.action in allowed_actions:
            return {"rbac_ok": True}

        try:
            await authorize_action.execute(state["request_ctx"].to_tenant_context(), action=proposed_action.action)
        except ActionNotPermittedError:
            return {"rbac_ok": False}
        return {"rbac_ok": True}

    return rbac_gate
