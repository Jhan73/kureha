"""Task 4.6: `ConfirmAccountLink` -- links a federated subject to an
existing password-based account, only after the caller has already obtained
explicit confirmation (spec `user-authentication` -> "Email Verification for
Account Linking": never a silent auto-merge on email match alone). Fake
ports only, no DB."""

from datetime import datetime, timezone

import pytest

from app.modules.identity.application.use_cases.confirm_account_link import ConfirmAccountLink
from app.modules.identity.domain.errors import InactiveUserError, UnmappedIdentityError
from app.modules.identity.domain.login_result import LoginResult
from app.modules.identity.domain.refresh_session import RefreshSession
from app.modules.identity.domain.user_account import UserAccount

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _user(**overrides) -> UserAccount:
    defaults = dict(
        id="existing-user",
        tenant_id="t1",
        site_id="s1",
        role="patient",
        status="active",
        email="a@example.com",
        auth_subject=None,
        email_verified_at=None,
    )
    defaults.update(overrides)
    return UserAccount(**defaults)


class _FakeUserDirectory:
    def __init__(self, *, users: dict[str, UserAccount] | None = None) -> None:
        self._users = users or {}
        self.link_calls: list[dict] = []

    async def find_by_email(self, tenant_id, email):
        raise NotImplementedError

    async def find_by_auth_subject(self, tenant_id, auth_subject):
        raise NotImplementedError

    async def get_by_id(self, tenant_id, user_id):
        return self._users.get(user_id)

    async def link_auth_subject(self, tenant_id, user_id, *, auth_subject, email_verified):
        self.link_calls.append(
            {"tenant_id": tenant_id, "user_id": user_id, "auth_subject": auth_subject, "email_verified": email_verified}
        )
        original = self._users[user_id]
        linked = UserAccount(
            id=original.id,
            tenant_id=original.tenant_id,
            site_id=original.site_id,
            role=original.role,
            status=original.status,
            email=original.email,
            auth_subject=auth_subject,
            email_verified_at=_NOW if email_verified else None,
        )
        self._users[user_id] = linked
        return linked

    async def provision_patient_user(self, tenant_id, *, site_id, email, auth_subject, email_verified):
        raise NotImplementedError


class _FakeSessionStore:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, tenant_id, user_id, *, refresh_token_hash, expires_at, rotated_from=None):
        self.created.append({"tenant_id": tenant_id, "user_id": user_id, "hash": refresh_token_hash})
        return RefreshSession(
            id="sess1",
            tenant_id=tenant_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            issued_at=_NOW,
            expires_at=expires_at,
            rotated_from=rotated_from,
            revoked_at=None,
            last_used_at=None,
        )

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
        raise NotImplementedError


class _FakeTokenIssuer:
    async def issue(self, ctx, *, ttl):
        return f"access-for-{ctx.actor_id}"


class _FakeSecretGenerator:
    def generate(self) -> str:
        return "opaque-refresh"


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


def _build(user_directory, session_store=None):
    return ConfirmAccountLink(
        user_directory=user_directory,
        session_store=session_store or _FakeSessionStore(),
        token_issuer=_FakeTokenIssuer(),
        secret_generator=_FakeSecretGenerator(),
        clock=_FixedClock(),
    )


@pytest.mark.asyncio
async def test_confirms_link_and_mints_a_fresh_token_pair() -> None:
    user = _user()
    directory = _FakeUserDirectory(users={"existing-user": user})
    session_store = _FakeSessionStore()
    use_case = _build(directory, session_store)

    result = await use_case.execute("t1", user_id="existing-user", auth_subject="google-sub-new", email_verified=True)

    assert isinstance(result, LoginResult)
    assert result.user.auth_subject == "google-sub-new"
    assert directory.link_calls == [
        {"tenant_id": "t1", "user_id": "existing-user", "auth_subject": "google-sub-new", "email_verified": True}
    ]
    assert session_store.created[0]["user_id"] == "existing-user"


@pytest.mark.asyncio
async def test_raises_when_the_user_no_longer_exists() -> None:
    directory = _FakeUserDirectory(users={})
    use_case = _build(directory)

    with pytest.raises(UnmappedIdentityError):
        await use_case.execute("t1", user_id="ghost", auth_subject="sub", email_verified=True)


@pytest.mark.asyncio
async def test_raises_when_the_user_is_not_active_and_mints_no_token() -> None:
    user = _user(status="inactive")
    directory = _FakeUserDirectory(users={"existing-user": user})
    use_case = _build(directory)

    with pytest.raises(InactiveUserError):
        await use_case.execute("t1", user_id="existing-user", auth_subject="google-sub-new", email_verified=True)

    assert directory.link_calls == []  # no linking, no token minted
