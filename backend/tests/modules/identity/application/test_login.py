from datetime import datetime, timedelta, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.use_cases.login import Login
from app.modules.identity.domain.authn_result import AuthnResult
from app.modules.identity.domain.errors import InactiveUserError, InvalidCredentialsError, UnmappedIdentityError
from app.modules.identity.domain.login_result import AccountLinkRequired, LoginResult
from app.modules.identity.domain.refresh_session import RefreshSession
from app.modules.identity.domain.refresh_token_hash import hash_refresh_token
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
        auth_subject=None,
        email_verified_at=None,
    )
    defaults.update(overrides)
    return UserAccount(**defaults)


class _FakeAuth:
    def __init__(self, *, password_result=None, federated_result=None, raises: Exception | None = None) -> None:
        self._password_result = password_result
        self._federated_result = federated_result
        self._raises = raises

    async def verify_password(self, email: str, password: str) -> AuthnResult:
        if self._raises:
            raise self._raises
        return self._password_result

    async def verify_federated(self, provider, id_token: str) -> AuthnResult:
        if self._raises:
            raise self._raises
        return self._federated_result

    async def start_password_reset(self, email: str) -> None:
        raise NotImplementedError


class _FakeUserDirectory:
    def __init__(self, *, by_email=None, by_subject=None) -> None:
        self._by_email = by_email or {}
        self._by_subject = by_subject or {}
        self.provisioned: list[dict] = []
        self.linked: list[dict] = []

    async def find_by_email(self, tenant_id, email):
        return self._by_email.get((tenant_id, email))

    async def find_by_auth_subject(self, tenant_id, auth_subject):
        return self._by_subject.get((tenant_id, auth_subject))

    async def get_by_id(self, tenant_id, user_id):
        raise NotImplementedError

    async def link_auth_subject(self, tenant_id, user_id, *, auth_subject, email_verified):
        raise NotImplementedError

    async def provision_patient_user(self, tenant_id, *, site_id, email, auth_subject, email_verified):
        user = _user(id="new-user", tenant_id=tenant_id, site_id=site_id, role="patient", auth_subject=auth_subject)
        self.provisioned.append(
            {"tenant_id": tenant_id, "site_id": site_id, "email": email, "auth_subject": auth_subject}
        )
        return user


class _FakeSessionStore:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create(self, tenant_id, user_id, *, refresh_token_hash, expires_at, rotated_from=None):
        self.created.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "refresh_token_hash": refresh_token_hash,
                "expires_at": expires_at,
            }
        )
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
    def __init__(self, value: str = "opaque-refresh-secret") -> None:
        self._value = value

    def generate(self) -> str:
        return self._value


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> str:
        self.recorded.append(entry)
        return "audit-1"


class _FakeClock:
    def now(self) -> datetime:
        return _NOW


def _build_login(auth, user_directory, session_store=None, audit_log=None):
    return Login(
        auth=auth,
        user_directory=user_directory,
        session_store=session_store or _FakeSessionStore(),
        token_issuer=_FakeTokenIssuer(),
        secret_generator=_FakeSecretGenerator(),
        audit_log=audit_log or _FakeAuditLog(),
        clock=_FakeClock(),
    )


@pytest.mark.asyncio
async def test_password_login_mints_access_and_refresh_for_mapped_user() -> None:
    user = _user()
    auth = _FakeAuth(password_result=AuthnResult(subject="sub1", email="a@example.com", email_verified=True, provider="password"))
    directory = _FakeUserDirectory(by_email={("t1", "a@example.com"): user})
    session_store = _FakeSessionStore()

    login = _build_login(auth, directory, session_store)
    result = await login.with_password("t1", email="a@example.com", password="correct-horse")

    assert isinstance(result, LoginResult)
    assert result.access_token == "access-for-u1"
    assert result.refresh_token == "opaque-refresh-secret"
    assert result.user == user
    assert session_store.created[0]["refresh_token_hash"] == hash_refresh_token("opaque-refresh-secret")
    assert session_store.created[0]["expires_at"] == _NOW + timedelta(days=30)


@pytest.mark.asyncio
async def test_password_login_propagates_invalid_credentials() -> None:
    auth = _FakeAuth(raises=InvalidCredentialsError())
    directory = _FakeUserDirectory()
    login = _build_login(auth, directory)

    with pytest.raises(InvalidCredentialsError):
        await login.with_password("t1", email="nobody@example.com", password="wrong")


@pytest.mark.asyncio
async def test_password_login_denies_and_audits_unmapped_identity() -> None:
    auth = _FakeAuth(password_result=AuthnResult(subject="sub1", email="ghost@example.com", email_verified=True, provider="password"))
    directory = _FakeUserDirectory()  # no matching users row
    audit_log = _FakeAuditLog()
    login = _build_login(auth, directory, audit_log=audit_log)

    with pytest.raises(UnmappedIdentityError):
        await login.with_password("t1", email="ghost@example.com", password="whatever")

    assert len(audit_log.recorded) == 1
    entry = audit_log.recorded[0]
    assert entry.tenant_id == "t1"
    assert entry.actor_type == AuditActorType.SYSTEM
    assert entry.action == AuditAction.AUTH_UNMAPPED_IDENTITY
    assert entry.actor_id is None
    assert entry.payload["email"] == "ghost@example.com"
    assert entry.payload["subject"] == "sub1"


@pytest.mark.asyncio
async def test_password_login_denies_inactive_user() -> None:
    user = _user(status="inactive")
    auth = _FakeAuth(password_result=AuthnResult(subject="sub1", email="a@example.com", email_verified=True, provider="password"))
    directory = _FakeUserDirectory(by_email={("t1", "a@example.com"): user})
    login = _build_login(auth, directory)

    with pytest.raises(InactiveUserError):
        await login.with_password("t1", email="a@example.com", password="correct-horse")


@pytest.mark.asyncio
async def test_google_login_resolves_existing_linked_user_by_subject() -> None:
    user = _user(auth_subject="google-sub-1")
    auth = _FakeAuth(federated_result=AuthnResult(subject="google-sub-1", email="a@example.com", email_verified=True, provider="google"))
    directory = _FakeUserDirectory(by_subject={("t1", "google-sub-1"): user})
    login = _build_login(auth, directory)

    result = await login.with_google("t1", id_token="raw-id-token")

    assert isinstance(result, LoginResult)
    assert result.user == user


@pytest.mark.asyncio
async def test_google_login_first_time_with_default_site_provisions_a_patient() -> None:
    auth = _FakeAuth(federated_result=AuthnResult(subject="google-sub-new", email="new@example.com", email_verified=True, provider="google"))
    directory = _FakeUserDirectory()
    login = _build_login(auth, directory)

    result = await login.with_google("t1", id_token="raw-id-token", default_site_id="site-1")

    assert isinstance(result, LoginResult)
    assert directory.provisioned == [
        {"tenant_id": "t1", "site_id": "site-1", "email": "new@example.com", "auth_subject": "google-sub-new"}
    ]


@pytest.mark.asyncio
async def test_google_login_first_time_without_default_site_denies_and_audits() -> None:
    auth = _FakeAuth(federated_result=AuthnResult(subject="google-sub-new", email="new@example.com", email_verified=True, provider="google"))
    directory = _FakeUserDirectory()
    audit_log = _FakeAuditLog()
    login = _build_login(auth, directory, audit_log=audit_log)

    with pytest.raises(UnmappedIdentityError):
        await login.with_google("t1", id_token="raw-id-token")

    assert len(audit_log.recorded) == 1
    entry = audit_log.recorded[0]
    assert entry.action == AuditAction.AUTH_UNMAPPED_IDENTITY
    assert entry.payload["email"] == "new@example.com"
    assert entry.payload["subject"] == "google-sub-new"


@pytest.mark.asyncio
async def test_google_login_conflicting_email_already_linked_to_a_different_subject_denies_and_audits() -> None:
    existing = _user(id="existing-user", auth_subject="google-sub-already-linked")
    auth = _FakeAuth(
        federated_result=AuthnResult(
            subject="google-sub-attacker", email="a@example.com", email_verified=True, provider="google"
        )
    )
    directory = _FakeUserDirectory(by_email={("t1", "a@example.com"): existing})
    audit_log = _FakeAuditLog()
    login = _build_login(auth, directory, audit_log=audit_log)

    with pytest.raises(UnmappedIdentityError):
        await login.with_google("t1", id_token="raw-id-token")

    assert len(audit_log.recorded) == 1
    entry = audit_log.recorded[0]
    assert entry.action == AuditAction.AUTH_UNMAPPED_IDENTITY
    assert entry.payload["email"] == "a@example.com"
    assert entry.payload["subject"] == "google-sub-attacker"


@pytest.mark.asyncio
async def test_google_login_matching_existing_unlinked_password_account_requires_confirmation() -> None:
    existing = _user(id="existing-user", auth_subject=None)
    auth = _FakeAuth(federated_result=AuthnResult(subject="google-sub-new", email="a@example.com", email_verified=True, provider="google"))
    directory = _FakeUserDirectory(by_email={("t1", "a@example.com"): existing})
    session_store = _FakeSessionStore()
    login = _build_login(auth, directory, session_store)

    result = await login.with_google("t1", id_token="raw-id-token")

    assert result == AccountLinkRequired(
        existing_user_id="existing-user", email="a@example.com", pending_subject="google-sub-new", email_verified=True
    )
    assert session_store.created == []  # no token minted -- linking not yet confirmed
