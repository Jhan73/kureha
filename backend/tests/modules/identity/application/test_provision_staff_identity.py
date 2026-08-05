"""`ProvisionStaffIdentity` use case (staff-invite batch, design.md §17
extension): invites a new staff member's email via `AuthPort.invite_user`
and creates the corresponding `users`/`user_credentials` rows via
`UserDirectoryPort.provision_staff_user` -- the identity-module half of
`POST /staff/register`'s new invite flow (the other half, `RegisterStaff`,
is unchanged and already tested). Fake ports only, no DB -- mirrors
`test_login.py`'s own convention."""

from datetime import datetime, timezone

import pytest

from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.identity.application.use_cases.provision_staff_identity import ProvisionStaffIdentity
from app.modules.identity.domain.authn_result import AuthnResult
from app.modules.identity.domain.errors import EmailAlreadyRegisteredError
from app.modules.identity.domain.user_account import UserAccount
from app.shared_kernel.errors import ValidationError

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _user(**overrides) -> UserAccount:
    defaults = dict(
        id="new-user-1",
        tenant_id="t1",
        site_id="s1",
        role="reception",
        status="active",
        email="new-staff@example.com",
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
    def __init__(self, *, existing_by_email=None) -> None:
        self._existing_by_email = existing_by_email or {}
        self.provisioned: list[dict] = []

    async def find_by_email(self, tenant_id, email):
        return self._existing_by_email.get((tenant_id, email))

    async def find_by_auth_subject(self, tenant_id, auth_subject):
        raise NotImplementedError

    async def get_by_id(self, tenant_id, user_id):
        raise NotImplementedError

    async def link_auth_subject(self, tenant_id, user_id, *, auth_subject, email_verified):
        raise NotImplementedError

    async def provision_patient_user(self, tenant_id, *, site_id, email, auth_subject, email_verified):
        raise NotImplementedError

    async def provision_staff_user(
        self, tenant_id, *, site_id, role, email, auth_subject, email_verified, professional_id=None
    ):
        self.provisioned.append(
            {
                "tenant_id": tenant_id,
                "site_id": site_id,
                "role": role,
                "email": email,
                "auth_subject": auth_subject,
                "email_verified": email_verified,
                "professional_id": professional_id,
            }
        )
        return _user(
            tenant_id=tenant_id,
            site_id=site_id,
            role=role,
            email=email,
            auth_subject=auth_subject,
            email_verified_at=_NOW if email_verified else None,
        )


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list[AuditEntry] = []

    async def record(self, entry: AuditEntry) -> str:
        self.recorded.append(entry)
        return "audit-1"


_INVITE_REDIRECT_URL = "https://app.example.com/staff/login"


def _build(auth, user_directory, audit_log=None):
    return ProvisionStaffIdentity(auth, user_directory, audit_log or _FakeAuditLog(), _INVITE_REDIRECT_URL)


@pytest.mark.asyncio
async def test_provisions_a_new_staff_identity_via_invite() -> None:
    auth = _FakeAuth(
        invited_result=AuthnResult(
            subject="supabase-invited-sub", email="new-staff@example.com", email_verified=False, provider="password"
        )
    )
    directory = _FakeUserDirectory()
    use_case = _build(auth, directory)

    account = await use_case.execute(
        "t1", site_id="s1", email="new-staff@example.com", role="reception", actor_id="admin-1"
    )

    assert account.email == "new-staff@example.com"
    assert account.role == "reception"
    assert auth.invited_emails == ["new-staff@example.com"]
    assert auth.invite_redirect_urls == [_INVITE_REDIRECT_URL]
    assert directory.provisioned == [
        {
            "tenant_id": "t1",
            "site_id": "s1",
            "role": "reception",
            "email": "new-staff@example.com",
            "auth_subject": "supabase-invited-sub",
            "email_verified": False,
            "professional_id": None,
        }
    ]


@pytest.mark.asyncio
async def test_records_an_audit_entry_for_the_new_credential() -> None:
    auth = _FakeAuth(
        invited_result=AuthnResult(
            subject="sub-1", email="new-staff@example.com", email_verified=False, provider="password"
        )
    )
    directory = _FakeUserDirectory()
    audit_log = _FakeAuditLog()
    use_case = _build(auth, directory, audit_log)

    account = await use_case.execute(
        "t1", site_id="s1", email="new-staff@example.com", role="admin", actor_id="admin-1"
    )

    assert len(audit_log.recorded) == 1
    entry = audit_log.recorded[0]
    assert entry.tenant_id == "t1"
    assert entry.site_id == "s1"
    assert entry.actor_id == "admin-1"
    assert entry.actor_type == AuditActorType.USER
    assert entry.action == AuditAction.AUTH_CREDENTIAL_CREATED
    assert entry.object_type == "user"
    assert entry.object_id == account.id
    assert entry.payload["email"] == "new-staff@example.com"
    assert entry.payload["role"] == "admin"


@pytest.mark.asyncio
async def test_rejects_an_already_registered_email_without_inviting() -> None:
    existing = _user()
    auth = _FakeAuth()
    directory = _FakeUserDirectory(existing_by_email={("t1", "new-staff@example.com"): existing})
    use_case = _build(auth, directory)

    with pytest.raises(EmailAlreadyRegisteredError):
        await use_case.execute("t1", site_id="s1", email="new-staff@example.com", role="reception")

    # Never invited -- the duplicate check runs BEFORE calling Supabase.
    assert auth.invited_emails == []
    assert directory.provisioned == []


@pytest.mark.asyncio
async def test_professional_role_without_a_professional_id_is_rejected_before_inviting() -> None:
    """`users.professional_id IS NOT NULL` is a hard DB CHECK for
    `role='professional'` (migration 8fc0dc6f958d) -- validated up front as
    a clean `ValidationError`, not left to leak as a raw `IntegrityError`."""
    auth = _FakeAuth()
    directory = _FakeUserDirectory()
    use_case = _build(auth, directory)

    with pytest.raises(ValidationError):
        await use_case.execute("t1", site_id="s1", email="new-prof@example.com", role="professional")

    assert auth.invited_emails == []


@pytest.mark.asyncio
async def test_professional_role_with_a_professional_id_is_accepted() -> None:
    auth = _FakeAuth(
        invited_result=AuthnResult(subject="sub-p", email="prof@example.com", email_verified=False, provider="password")
    )
    directory = _FakeUserDirectory()
    use_case = _build(auth, directory)

    account = await use_case.execute(
        "t1", site_id="s1", email="prof@example.com", role="professional", professional_id="prof-123"
    )

    assert account.role == "professional"
    assert directory.provisioned[0]["professional_id"] == "prof-123"
