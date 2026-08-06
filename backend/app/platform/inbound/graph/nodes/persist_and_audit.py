from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncConnection

from app.composition_root import (
    build_cancel_appointment,
    build_create_shift,
    build_deactivate_staff,
    build_edit_shift,
    build_register_staff,
    build_reschedule_appointment,
    build_schedule_appointment,
    build_send_reminder,
)
from app.modules.governance.rbac.domain.permission import ActionKey
from app.platform.inbound.graph.state import ActionOutcome, KurehaState

_DISPATCH: dict[ActionKey, Callable[[AsyncConnection], Any]] = {
    "appointment:create": build_schedule_appointment,
    "appointment:reschedule": build_reschedule_appointment,
    "appointment:cancel": build_cancel_appointment,
    "appointment:view": build_send_reminder,
    "staff:register": build_register_staff,
    "staff:deactivate": build_deactivate_staff,
    "shift:create": build_create_shift,
    "shift:edit": build_edit_shift,
}


class UnroutableActionError(Exception):
    """No `_DISPATCH` entry for `proposed_action.action`."""

    def __init__(self, action: ActionKey) -> None:
        super().__init__(f"No persist_and_audit dispatch registered for action {action!r}")
        self.action = action


def make_persist_and_audit_node(conn: AsyncConnection, *, dispatch: dict[ActionKey, Callable] | None = None):
    """`dispatch` override is for tests only."""
    table = dispatch if dispatch is not None else _DISPATCH

    async def persist_and_audit(state: KurehaState) -> dict:
        proposed_action = state["proposed_action"]
        ctx = state["request_ctx"].to_tenant_context()

        builder = table.get(proposed_action.action)
        if builder is None:
            raise UnroutableActionError(proposed_action.action)

        use_case = builder(conn)
        result = await use_case.execute(ctx, **proposed_action.payload)

        outcome = ActionOutcome(success=True, result_id=getattr(result, "id", None), error=None)
        return {"outcome": outcome}

    return persist_and_audit
