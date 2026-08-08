import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.use_cases.invite_existing_user import InviteExistingUser
from app.modules.identity.domain.authn_result import AuthnResult
from app.modules.identity.domain.errors import CredentialInvitationFailedError
from app.modules.identity.domain.user_account import UserAccount


def _user(**overrides) -> UserAccount:
    defaults = dict(
        id="admin-1",
        tenant_id="t1",
        site_id="s1",
        role="admin",
        status="active",
        email="admin@example.com",
        auth_subject="supabase-invited-sub",
        email_verified_at=None,
    )
    defaults.update(overrides)
    return UserAccount(**defaults)


class _FakeAuth:
    def __init__(self, *, invited_result=None, raises: Exception | None = None) -> None:
        self._invited_result = invited_result
        self._raises = raises
        self.invited_emails: list[str] = []
        self.invite_redirect_urls: list[str] = []

    async def verify_password(self, email, password):
        raise NotImplementedError

    async def verify_federated(self, provider, id_token):
        raise NotImplementedError

    async def start_password_reset(self, email, redirect_to):
        raise NotImplementedError

    async def invite_user(self, email: str, redirect_to: str) -> AuthnResult:
        self.invited_emails.append(email)
        self.invite_redirect_urls.append(redirect_to)
        if self._raises:
            raise self._raises
        return self._invited_result

    async def complete_password_reset(self, recovery_token, new_password):
        raise NotImplementedError


class _FakeUserDirectory:
    def __init__(self) -> None:
        self.linked: list[dict] = []

    async def find_by_email(self, tenant_id, email):
        raise NotImplementedError

    async def find_by_auth_subject(self, tenant_id, auth_subject):
        raise NotImplementedError

    async def get_by_id(self, tenant_id, user_id):
        raise NotImplementedError

    async def link_auth_subject(self, tenant_id, user_id, *, auth_subject, email_verified):
        self.linked.append(
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "auth_subject": auth_subject,
                "email_verified": email_verified,
            }
        )
        return _user(tenant_id=tenant_id, id=user_id, auth_subject=auth_subject)

    async def provision_patient_user(self, tenant_id, *, site_id, email, auth_subject, email_verified):
        raise NotImplementedError

    async def provision_staff_user(
        self, tenant_id, *, site_id, role, email, auth_subject, email_verified, professional_id=None
    ):
        raise NotImplementedError


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> str:
        self.recorded.append(entry)
        return "audit-1"


_INVITE_REDIRECT_URL = "https://app.example.com/staff/login"


def _build(auth, user_directory, audit_log=None):
    return InviteExistingUser(auth, user_directory, audit_log or _FakeAuditLog(), _INVITE_REDIRECT_URL)


@pytest.mark.asyncio
async def test_invites_an_existing_user_and_links_the_auth_subject() -> None:
    auth = _FakeAuth(
        invited_result=AuthnResult(
            subject="supabase-invited-sub", email="admin@example.com", email_verified=False, provider="password"
        )
    )
    directory = _FakeUserDirectory()
    use_case = _build(auth, directory)

    account = await use_case.execute("t1", user_id="admin-1", site_id="s1", email="admin@example.com")

    assert account.auth_subject == "supabase-invited-sub"
    assert auth.invited_emails == ["admin@example.com"]
    assert auth.invite_redirect_urls == [_INVITE_REDIRECT_URL]
    assert directory.linked == [
        {
            "tenant_id": "t1",
            "user_id": "admin-1",
            "auth_subject": "supabase-invited-sub",
            "email_verified": False,
        }
    ]


@pytest.mark.asyncio
async def test_records_an_audit_entry_for_the_new_credential() -> None:
    auth = _FakeAuth(
        invited_result=AuthnResult(
            subject="supabase-invited-sub", email="admin@example.com", email_verified=False, provider="password"
        )
    )
    directory = _FakeUserDirectory()
    audit_log = _FakeAuditLog()
    use_case = _build(auth, directory, audit_log)

    account = await use_case.execute("t1", user_id="admin-1", site_id="s1", email="admin@example.com")

    assert len(audit_log.recorded) == 1
    entry = audit_log.recorded[0]
    assert entry.tenant_id == "t1"
    assert entry.site_id == "s1"
    assert entry.actor_type == AuditActorType.SYSTEM
    assert entry.action == AuditAction.AUTH_CREDENTIAL_CREATED
    assert entry.object_type == "user"
    assert entry.object_id == account.id
    assert entry.payload["email"] == "admin@example.com"


@pytest.mark.asyncio
async def test_invite_failure_raises_a_typed_error_without_linking_the_auth_subject() -> None:
    auth = _FakeAuth(raises=RuntimeError("supabase unreachable"))
    directory = _FakeUserDirectory()
    audit_log = _FakeAuditLog()
    use_case = _build(auth, directory, audit_log)

    with pytest.raises(CredentialInvitationFailedError):
        await use_case.execute("t1", user_id="admin-1", site_id="s1", email="admin@example.com")

    assert directory.linked == []
    assert audit_log.recorded == []
