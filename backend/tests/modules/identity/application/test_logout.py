"""Task 4.5: `Logout` use case -- revokes the caller's own session
(design.md §17.4, spec `session-management` -> "User logs out"). Fake ports
only, no DB.

Takes a raw `refresh_token: str` (like `RefreshToken`), NOT a `session_id`
-- nothing in this module ever hands a client a `user_sessions.id` to send
back (fix, confirmed review finding): the client only ever holds the opaque
refresh token string, so `Logout` hashes it and looks the session up via
`SessionStorePort.find_by_hash`, mirroring `RefreshToken.execute` exactly."""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.identity.application.use_cases.logout import Logout
from app.modules.identity.domain.errors import SessionNotFoundError
from app.modules.identity.domain.refresh_session import RefreshSession
from app.modules.identity.domain.refresh_token_hash import hash_refresh_token
from app.shared_kernel.tenant_context import TenantContext

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_PLAINTEXT = "the-callers-refresh-token"
_HASH = hash_refresh_token(_PLAINTEXT)


def _session(**overrides) -> RefreshSession:
    defaults = dict(
        id="sess1",
        tenant_id="t1",
        user_id="u1",
        refresh_token_hash=_HASH,
        issued_at=_NOW - timedelta(days=1),
        expires_at=_NOW + timedelta(days=29),
        rotated_from=None,
        revoked_at=None,
        last_used_at=None,
    )
    defaults.update(overrides)
    return RefreshSession(**defaults)


class _FakeSessionStore:
    def __init__(self, *, sessions: dict[str, RefreshSession] | None = None) -> None:
        self._by_hash = {s.refresh_token_hash: s for s in (sessions or {}).values()}
        self.revoked: list[str] = []

    async def create(self, *args, **kwargs):
        raise NotImplementedError

    async def get_by_id(self, tenant_id, session_id):
        raise NotImplementedError

    async def find_by_hash(self, refresh_token_hash):
        return self._by_hash.get(refresh_token_hash)

    async def find_successor(self, session_id):
        raise NotImplementedError

    async def revoke(self, session_id, *, revoked_at):
        self.revoked.append(session_id)

    async def rotate(self, old_session_id, tenant_id, user_id, *, refresh_token_hash, expires_at, revoked_at):
        raise NotImplementedError

    async def revoke_chain(self, session_id, *, revoked_at):
        raise NotImplementedError

    async def revoke_all_for_user(self, tenant_id, user_id, *, revoked_at):
        raise NotImplementedError


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


def _ctx(**overrides) -> TenantContext:
    defaults = dict(tenant_id="t1", role="reception", site_id="s1", actor_id="u1")
    defaults.update(overrides)
    return TenantContext(**defaults)


@pytest.mark.asyncio
async def test_logout_revokes_the_callers_own_session() -> None:
    session_store = _FakeSessionStore(sessions={"sess1": _session()})
    use_case = Logout(session_store, _FixedClock())

    await use_case.execute(_ctx(), refresh_token=_PLAINTEXT)

    assert session_store.revoked == ["sess1"]


@pytest.mark.asyncio
async def test_logout_rejects_a_session_belonging_to_another_user() -> None:
    session_store = _FakeSessionStore(sessions={"sess1": _session(user_id="someone-else")})
    use_case = Logout(session_store, _FixedClock())

    with pytest.raises(SessionNotFoundError):
        await use_case.execute(_ctx(), refresh_token=_PLAINTEXT)

    assert session_store.revoked == []


@pytest.mark.asyncio
async def test_logout_rejects_an_unknown_refresh_token() -> None:
    session_store = _FakeSessionStore(sessions={})
    use_case = Logout(session_store, _FixedClock())

    with pytest.raises(SessionNotFoundError):
        await use_case.execute(_ctx(), refresh_token="never-issued")


@pytest.mark.asyncio
async def test_logout_rejects_a_session_from_another_tenant() -> None:
    session_store = _FakeSessionStore(sessions={"sess1": _session(tenant_id="other-tenant")})
    use_case = Logout(session_store, _FixedClock())

    with pytest.raises(SessionNotFoundError):
        await use_case.execute(_ctx(), refresh_token=_PLAINTEXT)
