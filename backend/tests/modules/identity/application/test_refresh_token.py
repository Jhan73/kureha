"""Task 4.4: `RefreshToken` use case -- validate+rotate, 30s grace period,
reuse-detection revokes the chain, re-checks live active status, re-resolves
role (design.md §17.4). Fake ports only, no DB."""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.identity.application.use_cases.refresh_token import RefreshToken
from app.modules.identity.domain.errors import (
    InactiveUserError,
    InvalidRefreshTokenError,
    RefreshReuseDetectedError,
)
from app.modules.identity.domain.login_result import LoginResult
from app.modules.identity.domain.refresh_session import RefreshSession
from app.modules.identity.domain.refresh_token_hash import hash_refresh_token
from app.modules.identity.domain.user_account import UserAccount

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_OLD_PLAINTEXT = "old-refresh-plaintext"
_OLD_HASH = hash_refresh_token(_OLD_PLAINTEXT)


def _session(**overrides) -> RefreshSession:
    defaults = dict(
        id="sess-old",
        tenant_id="t1",
        user_id="u1",
        refresh_token_hash=_OLD_HASH,
        issued_at=_NOW - timedelta(days=1),
        expires_at=_NOW + timedelta(days=29),
        rotated_from=None,
        revoked_at=None,
        last_used_at=None,
    )
    defaults.update(overrides)
    return RefreshSession(**defaults)


def _user(**overrides) -> UserAccount:
    defaults = dict(
        id="u1",
        tenant_id="t1",
        site_id="s1",
        role="reception",
        status="active",
        email="a@example.com",
        auth_subject=None,
        email_verified_at=None,
    )
    defaults.update(overrides)
    return UserAccount(**defaults)


class _FakeSessionStore:
    def __init__(
        self,
        *,
        sessions: dict[str, RefreshSession] | None = None,
        successors: dict[str, RefreshSession] | None = None,
    ) -> None:
        self._by_hash = {s.refresh_token_hash: s for s in (sessions or {}).values()}
        # Keyed by the OLD session id whose rotation produced the value --
        # mirrors `SessionStorePort.find_successor`'s contract.
        self._successors = dict(successors or {})
        self.revoked: list[str] = []
        self.revoked_chains: list[str] = []
        self.created: list[dict] = []

    async def create(self, tenant_id, user_id, *, refresh_token_hash, expires_at, rotated_from=None):
        session = RefreshSession(
            id=f"sess-{len(self.created) + 1}",
            tenant_id=tenant_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            issued_at=_NOW,
            expires_at=expires_at,
            rotated_from=rotated_from,
            revoked_at=None,
            last_used_at=None,
        )
        self.created.append(
            {"tenant_id": tenant_id, "user_id": user_id, "hash": refresh_token_hash, "rotated_from": rotated_from}
        )
        self._by_hash[refresh_token_hash] = session
        return session

    async def find_by_hash(self, refresh_token_hash):
        return self._by_hash.get(refresh_token_hash)

    async def find_successor(self, session_id):
        return self._successors.get(session_id)

    async def revoke(self, session_id, *, revoked_at):
        self.revoked.append(session_id)
        for session in list(self._by_hash.values()):
            if session.id == session_id:
                updated = RefreshSession(
                    id=session.id,
                    tenant_id=session.tenant_id,
                    user_id=session.user_id,
                    refresh_token_hash=session.refresh_token_hash,
                    issued_at=session.issued_at,
                    expires_at=session.expires_at,
                    rotated_from=session.rotated_from,
                    revoked_at=revoked_at,
                    last_used_at=session.last_used_at,
                )
                self._by_hash[session.refresh_token_hash] = updated

    async def revoke_chain(self, session_id, *, revoked_at):
        self.revoked_chains.append(session_id)

    async def revoke_all_for_user(self, tenant_id, user_id, *, revoked_at):
        raise NotImplementedError

    async def rotate(self, old_session_id, tenant_id, user_id, *, refresh_token_hash, expires_at, revoked_at):
        # Single-round-trip combination of revoke+create (fix #10) --
        # expressed here as the two fake operations so every existing
        # assertion against `.revoked`/`.created` keeps working unchanged.
        await self.revoke(old_session_id, revoked_at=revoked_at)
        created = await self.create(
            tenant_id, user_id, refresh_token_hash=refresh_token_hash, expires_at=expires_at, rotated_from=old_session_id
        )
        self._successors[old_session_id] = created
        return created


class _FakeUserDirectory:
    def __init__(self, *, users: dict[str, UserAccount] | None = None) -> None:
        self._users = users or {}

    async def find_by_email(self, tenant_id, email):
        raise NotImplementedError

    async def find_by_auth_subject(self, tenant_id, auth_subject):
        raise NotImplementedError

    async def get_by_id(self, tenant_id, user_id):
        return self._users.get(user_id)

    async def link_auth_subject(self, tenant_id, user_id, *, auth_subject, email_verified):
        raise NotImplementedError

    async def provision_patient_user(self, tenant_id, *, site_id, email, auth_subject, email_verified):
        raise NotImplementedError


class _FakeTokenIssuer:
    async def issue(self, ctx, *, ttl):
        return f"access-for-{ctx.actor_id}-{ctx.role}"


class _FakeSecretGenerator:
    def __init__(self, values: list[str]) -> None:
        self._values = iter(values)

    def generate(self) -> str:
        return next(self._values)


class _FakeReplayCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, str]] = {}

    def get(self, old_refresh_token_hash: str):
        return self._store.get(old_refresh_token_hash)

    def set(self, old_refresh_token_hash: str, *, access_token: str, refresh_token: str) -> None:
        self._store[old_refresh_token_hash] = (access_token, refresh_token)


class _FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _build(session_store, user_directory, *, replay_cache=None, secret_values=None, now=_NOW):
    return RefreshToken(
        session_store=session_store,
        user_directory=user_directory,
        token_issuer=_FakeTokenIssuer(),
        secret_generator=_FakeSecretGenerator(secret_values or ["new-refresh-plaintext"]),
        replay_cache=replay_cache or _FakeReplayCache(),
        clock=_FixedClock(now),
    )


@pytest.mark.asyncio
async def test_unknown_refresh_token_is_rejected() -> None:
    session_store = _FakeSessionStore()
    use_case = _build(session_store, _FakeUserDirectory())

    with pytest.raises(InvalidRefreshTokenError):
        await use_case.execute(refresh_token="never-issued")


@pytest.mark.asyncio
async def test_expired_refresh_token_is_rejected() -> None:
    session = _session(expires_at=_NOW - timedelta(seconds=1))
    session_store = _FakeSessionStore(sessions={"s": session})
    use_case = _build(session_store, _FakeUserDirectory())

    with pytest.raises(InvalidRefreshTokenError):
        await use_case.execute(refresh_token=_OLD_PLAINTEXT)


@pytest.mark.asyncio
async def test_valid_refresh_rotates_and_mints_new_access_reflecting_current_role() -> None:
    session = _session()
    session_store = _FakeSessionStore(sessions={"s": session})
    user = _user(role="admin")  # role changed since login -- must be reflected
    directory = _FakeUserDirectory(users={"u1": user})
    use_case = _build(session_store, directory, secret_values=["new-refresh-plaintext"])

    result = await use_case.execute(refresh_token=_OLD_PLAINTEXT)

    assert isinstance(result, LoginResult)
    assert result.access_token == "access-for-u1-admin"
    assert result.refresh_token == "new-refresh-plaintext"
    assert session_store.revoked == ["sess-old"]
    assert session_store.created[0]["rotated_from"] == "sess-old"
    assert session_store.created[0]["hash"] == hash_refresh_token("new-refresh-plaintext")


@pytest.mark.asyncio
async def test_valid_refresh_denies_inactive_user() -> None:
    session = _session()
    session_store = _FakeSessionStore(sessions={"s": session})
    directory = _FakeUserDirectory(users={"u1": _user(status="inactive")})
    use_case = _build(session_store, directory)

    with pytest.raises(InactiveUserError):
        await use_case.execute(refresh_token=_OLD_PLAINTEXT)

    assert session_store.revoked == []  # deny, but do not force-revoke the session


@pytest.mark.asyncio
async def test_valid_refresh_denies_when_user_no_longer_resolvable() -> None:
    session = _session()
    session_store = _FakeSessionStore(sessions={"s": session})
    directory = _FakeUserDirectory(users={})  # user row gone
    use_case = _build(session_store, directory)

    with pytest.raises(InactiveUserError):
        await use_case.execute(refresh_token=_OLD_PLAINTEXT)


@pytest.mark.asyncio
async def test_reuse_within_grace_period_replays_cached_pair() -> None:
    revoked_session = _session(revoked_at=_NOW - timedelta(seconds=10))
    successor = RefreshSession(
        id="sess-successor",
        tenant_id="t1",
        user_id="u1",
        refresh_token_hash="successor-hash",
        issued_at=_NOW - timedelta(seconds=10),
        expires_at=_NOW + timedelta(days=29),
        rotated_from="sess-old",
        revoked_at=None,
        last_used_at=None,
    )
    session_store = _FakeSessionStore(sessions={"s": revoked_session}, successors={"sess-old": successor})
    replay_cache = _FakeReplayCache()
    replay_cache.set(_OLD_HASH, access_token="cached-access", refresh_token="cached-refresh")
    directory = _FakeUserDirectory(users={"u1": _user()})
    use_case = _build(session_store, directory, replay_cache=replay_cache)

    result = await use_case.execute(refresh_token=_OLD_PLAINTEXT)

    assert result.access_token == "cached-access"
    assert result.refresh_token == "cached-refresh"
    assert session_store.revoked_chains == []  # not treated as theft
    assert session_store.created == []  # no second rotation performed


@pytest.mark.asyncio
async def test_reuse_within_grace_period_without_cache_hit_reuses_the_existing_successor() -> None:
    # A genuine rotation already happened (a successor exists) but this
    # instance's in-process replay cache missed it (design.md §17.4's
    # documented multi-instance limitation). Must NOT mint a second sibling
    # session from the same old parent -- only a fresh access token scoped
    # to the ONE successor that already exists.
    revoked_session = _session(revoked_at=_NOW - timedelta(seconds=10))
    successor = RefreshSession(
        id="sess-successor",
        tenant_id="t1",
        user_id="u1",
        refresh_token_hash="successor-hash",
        issued_at=_NOW - timedelta(seconds=10),
        expires_at=_NOW + timedelta(days=29),
        rotated_from="sess-old",
        revoked_at=None,
        last_used_at=None,
    )
    session_store = _FakeSessionStore(sessions={"s": revoked_session}, successors={"sess-old": successor})
    directory = _FakeUserDirectory(users={"u1": _user()})
    use_case = _build(session_store, directory)

    result = await use_case.execute(refresh_token=_OLD_PLAINTEXT)

    assert result.access_token == "access-for-u1-reception"
    assert result.refresh_token == _OLD_PLAINTEXT  # echoes the presented token, no new secret minted
    assert session_store.revoked_chains == []  # still not treated as theft
    assert session_store.created == []  # no sibling session created
    assert session_store.revoked == []  # no additional revoke either


@pytest.mark.asyncio
async def test_reuse_of_a_non_rotation_revocation_within_the_grace_window_is_rejected_not_reminted() -> None:
    # Revoked by logout/admin-revoke (or the terminal node of an earlier
    # chain-revoke) -- NOT rotation, so no successor exists. Grace-period
    # leniency must NOT apply: this is an ordinary revoked/invalid token,
    # not a rotation retry and not evidence of theft on its own.
    revoked_session = _session(revoked_at=_NOW - timedelta(seconds=10))
    session_store = _FakeSessionStore(sessions={"s": revoked_session})  # no successor registered
    use_case = _build(session_store, _FakeUserDirectory())

    with pytest.raises(InvalidRefreshTokenError):
        await use_case.execute(refresh_token=_OLD_PLAINTEXT)

    assert session_store.revoked_chains == []  # not escalated to a reuse-attack chain revoke
    assert session_store.created == []  # never silently re-minted


@pytest.mark.asyncio
async def test_reuse_past_grace_period_revokes_the_whole_chain_and_denies() -> None:
    # A genuine rotation happened (successor exists) and the old token is
    # being replayed past the grace window -- the actual reuse-attack
    # signal design.md §17.4 describes.
    revoked_session = _session(revoked_at=_NOW - timedelta(seconds=31))
    successor = RefreshSession(
        id="sess-successor",
        tenant_id="t1",
        user_id="u1",
        refresh_token_hash="successor-hash",
        issued_at=_NOW - timedelta(seconds=31),
        expires_at=_NOW + timedelta(days=29),
        rotated_from="sess-old",
        revoked_at=None,
        last_used_at=None,
    )
    session_store = _FakeSessionStore(sessions={"s": revoked_session}, successors={"sess-old": successor})
    use_case = _build(session_store, _FakeUserDirectory())

    with pytest.raises(RefreshReuseDetectedError):
        await use_case.execute(refresh_token=_OLD_PLAINTEXT)

    assert session_store.revoked_chains == ["sess-old"]
