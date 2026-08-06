from datetime import datetime, timedelta, timezone

import pytest

from app.modules.identity.application.use_cases.complete_password_reset import CompletePasswordReset
from app.modules.identity.domain.authn_result import AuthnResult
from app.modules.identity.domain.errors import InactiveUserError, InvalidCredentialsError, UnmappedIdentityError
from app.modules.identity.domain.login_result import LoginResult
from app.modules.identity.domain.refresh_session import RefreshSession
from app.modules.identity.domain.user_account import UserAccount

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _user(**overrides) -> UserAccount:
    defaults = dict(
        id="u1",
        tenant_id="t1",
        site_id="s1",
        role="reception",
        status="active",
        email="a@example.com",
        auth_subject="supabase-sub-1",
        email_verified_at=None,
    )
    defaults.update(overrides)
    return UserAccount(**defaults)


class _FakeAuth:
    def __init__(self, *, result=None, raises: Exception | None = None) -> None:
        self._result = result
        self._raises = raises

    async def verify_password(self, email, password):
        raise NotImplementedError

    async def verify_federated(self, provider, id_token):
        raise NotImplementedError

    async def start_password_reset(self, email):
        raise NotImplementedError

    async def invite_user(self, email):
        raise NotImplementedError

    async def complete_password_reset(self, recovery_token: str, new_password: str) -> AuthnResult:
        if self._raises:
            raise self._raises
        return self._result


class _FakeUserDirectory:
    def __init__(self, *, by_subject=None, by_email=None) -> None:
        self._by_subject = by_subject or {}
        self._by_email = by_email or {}

    async def find_by_email(self, tenant_id, email):
        return self._by_email.get((tenant_id, email))

    async def find_by_auth_subject(self, tenant_id, auth_subject):
        return self._by_subject.get((tenant_id, auth_subject))

    async def get_by_id(self, tenant_id, user_id):
        raise NotImplementedError

    async def link_auth_subject(self, tenant_id, user_id, *, auth_subject, email_verified):
        raise NotImplementedError

    async def provision_patient_user(self, tenant_id, *, site_id, email, auth_subject, email_verified):
        raise NotImplementedError

    async def provision_staff_user(
        self, tenant_id, *, site_id, role, email, auth_subject, email_verified, professional_id=None
    ):
        raise NotImplementedError


class _FakeSessionStore:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, tenant_id, user_id, *, refresh_token_hash, expires_at, rotated_from=None):
        self.created.append({"tenant_id": tenant_id, "user_id": user_id})
        return RefreshSession(
            id="sess1",
            tenant_id=tenant_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            issued_at=_NOW,
            expires_at=expires_at,
            rotated_from=None,
            revoked_at=None,
            last_used_at=None,
        )

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
        return "opaque-refresh-secret"


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded = []

    async def record_best_effort(self, entry) -> None:
        self.recorded.append(entry)


class _FakeClock:
    def now(self) -> datetime:
        return _NOW


def _build(auth, user_directory, session_store=None, audit_log=None):
    return CompletePasswordReset(
        auth=auth,
        user_directory=user_directory,
        session_store=session_store or _FakeSessionStore(),
        token_issuer=_FakeTokenIssuer(),
        secret_generator=_FakeSecretGenerator(),
        audit_log=audit_log or _FakeAuditLog(),
        clock=_FakeClock(),
    )


@pytest.mark.asyncio
async def test_completing_reset_resolves_by_auth_subject_and_mints_tokens() -> None:
    user = _user()
    auth = _FakeAuth(result=AuthnResult(subject="supabase-sub-1", email="a@example.com", email_verified=True, provider="password"))
    directory = _FakeUserDirectory(by_subject={("t1", "supabase-sub-1"): user})
    session_store = _FakeSessionStore()

    use_case = _build(auth, directory, session_store)
    result = await use_case.execute("t1", recovery_token="raw-recovery-token", new_password="new-correct-horse")

    assert isinstance(result, LoginResult)
    assert result.access_token == "access-for-u1"
    assert result.refresh_token == "opaque-refresh-secret"
    assert result.user == user
    assert session_store.created == [{"tenant_id": "t1", "user_id": "u1"}]


@pytest.mark.asyncio
async def test_completing_reset_falls_back_to_email_lookup_when_subject_is_unmapped() -> None:
    user = _user(auth_subject=None)
    auth = _FakeAuth(result=AuthnResult(subject="supabase-sub-new", email="a@example.com", email_verified=True, provider="password"))
    directory = _FakeUserDirectory(by_email={("t1", "a@example.com"): user})

    use_case = _build(auth, directory)
    result = await use_case.execute("t1", recovery_token="raw-recovery-token", new_password="new-correct-horse")

    assert result.user == user


@pytest.mark.asyncio
async def test_completing_reset_propagates_invalid_credentials_from_an_invalid_token() -> None:
    auth = _FakeAuth(raises=InvalidCredentialsError())
    directory = _FakeUserDirectory()
    use_case = _build(auth, directory)

    with pytest.raises(InvalidCredentialsError):
        await use_case.execute("t1", recovery_token="expired-token", new_password="new-password")


@pytest.mark.asyncio
async def test_completing_reset_denies_and_audits_an_unmapped_identity() -> None:
    auth = _FakeAuth(result=AuthnResult(subject="ghost-sub", email="ghost@example.com", email_verified=True, provider="password"))
    directory = _FakeUserDirectory()
    audit_log = _FakeAuditLog()
    use_case = _build(auth, directory, audit_log=audit_log)

    with pytest.raises(UnmappedIdentityError):
        await use_case.execute("t1", recovery_token="raw-token", new_password="new-password")

    assert len(audit_log.recorded) == 1


@pytest.mark.asyncio
async def test_completing_reset_denies_an_inactive_user() -> None:
    user = _user(status="inactive")
    auth = _FakeAuth(result=AuthnResult(subject="supabase-sub-1", email="a@example.com", email_verified=True, provider="password"))
    directory = _FakeUserDirectory(by_subject={("t1", "supabase-sub-1"): user})
    use_case = _build(auth, directory)

    with pytest.raises(InactiveUserError):
        await use_case.execute("t1", recovery_token="raw-token", new_password="new-password")
