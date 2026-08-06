from datetime import datetime, timezone

import pytest

from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.modules.identity.application.use_cases.revoke_session import RevokeAllSessionsForUser
from app.shared_kernel.tenant_context import TenantContext

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed
        self.checked_actions: list[str] = []

    async def is_allowed(self, ctx, action) -> bool:
        self.checked_actions.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx):
        raise NotImplementedError


class _FakeSessionStore:
    def __init__(self) -> None:
        self.revoked_calls: list[dict] = []

    async def create(self, *args, **kwargs):
        raise NotImplementedError

    async def get_by_id(self, tenant_id, session_id):
        raise NotImplementedError

    async def find_by_hash(self, refresh_token_hash):
        raise NotImplementedError

    async def find_successor(self, session_id):
        raise NotImplementedError

    async def revoke(self, session_id, *, revoked_at):
        raise NotImplementedError

    async def rotate(self, old_session_id, tenant_id, user_id, *, refresh_token_hash, expires_at, revoked_at):
        raise NotImplementedError

    async def revoke_chain(self, session_id, *, revoked_at):
        raise NotImplementedError

    async def revoke_all_for_user(self, tenant_id, user_id, *, revoked_at):
        self.revoked_calls.append({"tenant_id": tenant_id, "user_id": user_id, "revoked_at": revoked_at})
        return 3


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


def _admin_ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="admin", site_id="s1", actor_id="admin-1")


@pytest.mark.asyncio
async def test_admin_with_permission_revokes_all_sessions_for_the_target_user() -> None:
    authorization = _FakeAuthorizationPort(allowed=True)
    session_store = _FakeSessionStore()
    use_case = RevokeAllSessionsForUser(AuthorizeAction(authorization), session_store, _FixedClock())

    revoked_count = await use_case.execute(_admin_ctx(), target_user_id="target-user")

    assert revoked_count == 3
    assert authorization.checked_actions == ["session:revoke_all"]
    assert session_store.revoked_calls == [{"tenant_id": "t1", "user_id": "target-user", "revoked_at": _NOW}]


@pytest.mark.asyncio
async def test_denied_actor_cannot_revoke_and_repository_is_never_touched() -> None:
    authorization = _FakeAuthorizationPort(allowed=False)
    session_store = _FakeSessionStore()
    use_case = RevokeAllSessionsForUser(AuthorizeAction(authorization), session_store, _FixedClock())

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(_admin_ctx(), target_user_id="target-user")

    assert session_store.revoked_calls == []
