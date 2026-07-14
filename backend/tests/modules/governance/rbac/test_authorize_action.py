"""Task 3.5: `AuthorizeAction` use case -- deny raises `ActionNotPermittedError`
(design.md §5.3); allow is silent. No audit dependency here: auditing
`rbac.denied` is the `deny_action` platform node's job (Phase 11), not this
use case's -- see the module docstring for why."""

import pytest

from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.shared_kernel.tenant_context import TenantContext


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed
        self.checked_actions: list[str] = []

    async def is_allowed(self, ctx: TenantContext, action: str) -> bool:
        self.checked_actions.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx: TenantContext) -> set[str]:
        raise NotImplementedError


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")


@pytest.mark.asyncio
async def test_allowed_action_returns_without_raising() -> None:
    authorization = _FakeAuthorizationPort(allowed=True)
    use_case = AuthorizeAction(authorization)

    await use_case.execute(_ctx(), action="appointment:create")

    assert authorization.checked_actions == ["appointment:create"]


@pytest.mark.asyncio
async def test_denied_action_raises_action_not_permitted() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = AuthorizeAction(authorization)

    with pytest.raises(ActionNotPermittedError) as exc_info:
        await use_case.execute(_ctx(), action="appointment:cancel_bulk")

    assert exc_info.value.action == "appointment:cancel_bulk"


@pytest.mark.asyncio
async def test_denied_action_with_no_actor_id_still_raises_cleanly() -> None:
    """Regression: an anonymous/system TenantContext (actor_id=None) must
    deny cleanly. The old implementation hardcoded an audit write with
    actor_type=USER even when actor_id was None, which PR 3's RLS policy
    rejects for non-admin connections -- turning this into an unhandled 500
    instead of ActionNotPermittedError. Removing the inline audit call
    (this PR's fix) makes that failure mode structurally impossible here."""
    authorization = _FakeAuthorizationPort(allowed=False)
    use_case = AuthorizeAction(authorization)
    ctx = TenantContext(tenant_id="t1", role="reception", site_id="s1", actor_id=None)

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(ctx, action="staff:deactivate")
