"""Task 11.2: `rbac_gate` node -- authorizes `state.proposed_action` via
`AuthorizeAction`, with the in-memory `allowed_actions` shortcut design.md
§5.6/ADR-16 mandates (skip the second Postgres query when the action was
already loaded by `resolve_toolset` this request)."""

import pytest

from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.platform.inbound.graph.nodes.rbac_gate import make_rbac_gate_node
from app.platform.inbound.graph.state import KurehaState, ProposedAction, RequestContext


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed
        self.checked_actions: list[str] = []

    async def is_allowed(self, ctx, action: str) -> bool:
        self.checked_actions.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx) -> set[str]:
        raise NotImplementedError


class _ExplodingAuthorizationPort:
    """Used to prove the in-memory shortcut never reaches the port at all."""

    async def is_allowed(self, ctx, action: str) -> bool:
        raise AssertionError("AuthorizeAction must not be called when action is already in allowed_actions")

    async def list_allowed_actions(self, ctx) -> set[str]:
        raise AssertionError("must not be called")


def _state(*, allowed_actions: list[str] | None, proposed_action: ProposedAction | None) -> KurehaState:
    return {
        "request_ctx": RequestContext(tenant_id="t1", role="reception", site_id="s1", user_id="u1"),
        "channel": "staff_copilot",
        "channel_message": "x",
        "intent": "schedule",
        "scope_ok": True,
        "consent_ok": True,
        "allowed_actions": allowed_actions,
        "proposed_action": proposed_action,
        "rbac_ok": None,
        "risk_level": "low",
        "confirmation": None,
        "approval": None,
        "outcome": None,
        "audit_ref": None,
        "response_text": None,
        "response_scope_ok": None,
        "calendar_sync_status": None,
        "suggestions": None,
    }


def _proposed_action(action: str = "appointment:create") -> ProposedAction:
    return ProposedAction(action=action, is_mutating=True, payload={}, summary="s")


@pytest.mark.asyncio
async def test_in_memory_shortcut_skips_authorize_action_when_action_already_allowed() -> None:
    node = make_rbac_gate_node(_ExplodingAuthorizationPort())  # type: ignore[arg-type]
    state = _state(allowed_actions=["appointment:create"], proposed_action=_proposed_action("appointment:create"))

    result = await node(state)

    assert result == {"rbac_ok": True}


@pytest.mark.asyncio
async def test_falls_through_to_a_live_query_when_allowed_actions_is_none() -> None:
    port = _FakeAuthorizationPort(allowed=True)
    authorize_action = AuthorizeAction(port)
    node = make_rbac_gate_node(authorize_action)
    state = _state(allowed_actions=None, proposed_action=_proposed_action("appointment:create"))

    result = await node(state)

    assert result == {"rbac_ok": True}
    assert port.checked_actions == ["appointment:create"]


@pytest.mark.asyncio
async def test_falls_through_to_a_live_query_when_action_not_in_allowed_actions() -> None:
    port = _FakeAuthorizationPort(allowed=True)
    authorize_action = AuthorizeAction(port)
    node = make_rbac_gate_node(authorize_action)
    state = _state(allowed_actions=["appointment:view"], proposed_action=_proposed_action("appointment:cancel"))

    result = await node(state)

    assert result == {"rbac_ok": True}
    assert port.checked_actions == ["appointment:cancel"]


@pytest.mark.asyncio
async def test_live_query_denial_sets_rbac_ok_false() -> None:
    port = _FakeAuthorizationPort(allowed=False)
    authorize_action = AuthorizeAction(port)
    node = make_rbac_gate_node(authorize_action)
    state = _state(allowed_actions=None, proposed_action=_proposed_action("appointment:cancel_bulk"))

    result = await node(state)

    assert result == {"rbac_ok": False}


@pytest.mark.asyncio
async def test_no_proposed_action_denies_defensively() -> None:
    node = make_rbac_gate_node(_ExplodingAuthorizationPort())  # type: ignore[arg-type]
    state = _state(allowed_actions=["appointment:create"], proposed_action=None)

    result = await node(state)

    assert result == {"rbac_ok": False}
