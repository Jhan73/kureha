"""Task 11.2: `resolve_toolset` node -- delegates to `ListAllowedActions`
and stores the sorted result on `state.allowed_actions`."""

import pytest

from app.platform.inbound.graph.nodes.resolve_toolset import make_resolve_toolset_node
from app.platform.inbound.graph.state import KurehaState, RequestContext


class _FakeListAllowedActions:
    def __init__(self, *, actions: set[str]) -> None:
        self._actions = actions

    async def execute(self, ctx) -> set[str]:
        return self._actions


def _state() -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="reception", site_id="s1", user_id="u1"),
        "channel": "staff_copilot",
        "channel_message": "x",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": None,
        "proposed_action": None,
        "rbac_ok": None,
        "risk_level": None,
        "confirmation": None,
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


@pytest.mark.asyncio
async def test_resolve_toolset_stores_sorted_allowed_actions() -> None:
    list_allowed_actions = _FakeListAllowedActions(actions={"appointment:cancel", "appointment:create"})
    node = make_resolve_toolset_node(list_allowed_actions)

    result = await node(_state())

    assert result == {"allowed_actions": ["appointment:cancel", "appointment:create"]}


@pytest.mark.asyncio
async def test_resolve_toolset_handles_an_empty_set() -> None:
    list_allowed_actions = _FakeListAllowedActions(actions=set())
    node = make_resolve_toolset_node(list_allowed_actions)

    result = await node(_state())

    assert result == {"allowed_actions": []}
