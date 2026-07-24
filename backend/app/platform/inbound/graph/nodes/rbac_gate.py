"""`rbac_gate` node (design.md §5.6/§8.2, tasks.md task 11.2): authorizes
the concrete `proposed_action` a specialist node
(`scheduling_agent`/`reminders_agent`/`staff_agent`) already planned.
Deny-by-default via `AuthorizeAction` (design.md §5.3) -- BUT with the
in-memory shortcut design.md §5.6/ADR-16 mandates: if
`proposed_action.action` is already in `state.allowed_actions` (loaded
earlier THIS request by `resolve_toolset`), the check resolves without a
second Postgres round trip. Only falls through to
`AuthorizeAction.execute` (a live query) when `allowed_actions` is `None`
or does not already contain the action -- e.g. the turn-N+1 path design.md
§5.6 names explicitly, where `route_from_start` (task 11.6) skips
`resolve_toolset` entirely and jumps straight to `confirmation_gate`."""

from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.platform.inbound.graph.state import KurehaState


def make_rbac_gate_node(authorize_action: AuthorizeAction):
    async def rbac_gate(state: KurehaState) -> dict:
        proposed_action = state.get("proposed_action")
        if proposed_action is None:
            # Structurally unreachable via design.md §8.3's edges
            # (rbac_gate only follows a specialist node that always sets
            # proposed_action) -- guarded defensively rather than raising,
            # since a node's job is orchestration, not asserting invariants
            # about upstream nodes it does not control.
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
