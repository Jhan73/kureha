from app.modules.calendar.application.use_cases.connect_patient_calendar import ConnectPatientCalendar
from app.modules.calendar.domain.connect_calendar_result import CalendarConnected, CalendarEmailMismatch
from app.modules.calendar.domain.encrypted_secret import EncryptedSecret
from app.modules.governance.audit.domain.audit_entry import AuditAction
from app.modules.governance.rbac.application.use_cases.authorize_action import (
    ActionNotPermittedError,
    AuthorizeAction,
)
from app.shared_kernel.tenant_context import TenantContext

import pytest


class _FakeAuthorizationPort:
    def __init__(self, *, allowed: bool) -> None:
        self._allowed = allowed
        self.checked: list[str] = []

    async def is_allowed(self, ctx: TenantContext, action: str) -> bool:
        self.checked.append(action)
        return self._allowed

    async def list_allowed_actions(self, ctx: TenantContext) -> set[str]:
        raise NotImplementedError


class _FakePatientEmailLookup:
    def __init__(self, *, email: str | None) -> None:
        self._email = email

    async def get_registered_email(self, tenant_id: str, patient_id: str) -> str | None:
        return self._email


class _FakeCredentialVault:
    def __init__(self) -> None:
        self.encrypted: list[bytes] = []

    async def encrypt(self, plaintext: bytes) -> EncryptedSecret:
        self.encrypted.append(plaintext)
        return EncryptedSecret(ciphertext=b"cipher", nonce=b"n" * 12, wrapped_dek=b"wrapped", key_version=1)

    async def decrypt(self, secret: EncryptedSecret) -> bytes:
        raise NotImplementedError


class _FakeCredentialRepository:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def get(self, tenant_id, patient_id):
        raise NotImplementedError

    async def save(self, tenant_id, patient_id, secret, *, scope):
        self.saved.append({"tenant_id": tenant_id, "patient_id": patient_id, "scope": scope})
        return type("Row", (), {"id": "cred-1"})()

    async def revoke(self, tenant_id, patient_id):
        raise NotImplementedError


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return "audit-1"


def _ctx() -> TenantContext:
    return TenantContext(tenant_id="t1", role="patient", site_id="s1", actor_id="u1")


def _use_case(*, allowed=True, registered_email="a@example.com"):
    authorization = _FakeAuthorizationPort(allowed=allowed)
    email_lookup = _FakePatientEmailLookup(email=registered_email)
    vault = _FakeCredentialVault()
    repository = _FakeCredentialRepository()
    audit = _FakeAuditLog()
    use_case = ConnectPatientCalendar(
        AuthorizeAction(authorization), email_lookup, vault, repository, audit
    )
    return use_case, authorization, vault, repository, audit


async def test_authorize_is_checked_before_anything_else() -> None:
    use_case, authorization, *_ = _use_case(allowed=False)

    with pytest.raises(ActionNotPermittedError):
        await use_case.execute(
            _ctx(), patient_id="p1", google_email="a@example.com", refresh_token="rt", scope="scope"
        )

    assert authorization.checked == ["calendar:connect"]


async def test_matching_email_encrypts_and_saves_the_credential() -> None:
    use_case, _, vault, repository, audit = _use_case(registered_email="a@example.com")

    result = await use_case.execute(
        _ctx(), patient_id="p1", google_email="a@example.com", refresh_token="rt-secret", scope="scope"
    )

    assert isinstance(result, CalendarConnected)
    assert result.credential_id == "cred-1"
    assert vault.encrypted == [b"rt-secret"]
    assert repository.saved == [{"tenant_id": "t1", "patient_id": "p1", "scope": "scope"}]
    assert len(audit.recorded) == 1
    assert audit.recorded[0].action == AuditAction.CALENDAR_CONNECT
    assert audit.recorded[0].payload["status"] == "connected"


async def test_matching_email_is_case_insensitive() -> None:
    use_case, *_rest, repository, _audit = _use_case(registered_email="A@Example.com")

    result = await use_case.execute(
        _ctx(), patient_id="p1", google_email="a@example.com", refresh_token="rt", scope="scope"
    )

    assert isinstance(result, CalendarConnected)
    assert repository.saved


async def test_no_registered_email_on_file_still_connects() -> None:
    use_case, *_rest, repository, _audit = _use_case(registered_email=None)

    result = await use_case.execute(
        _ctx(), patient_id="p1", google_email="a@example.com", refresh_token="rt", scope="scope"
    )

    assert isinstance(result, CalendarConnected)
    assert repository.saved


async def test_mismatched_email_returns_mismatch_without_persisting_anything() -> None:
    use_case, _, vault, repository, audit = _use_case(registered_email="a@example.com")

    result = await use_case.execute(
        _ctx(), patient_id="p1", google_email="b@example.com", refresh_token="rt", scope="scope"
    )

    assert isinstance(result, CalendarEmailMismatch)
    assert result.registered_email == "a@example.com"
    assert result.google_email == "b@example.com"
    assert vault.encrypted == []
    assert repository.saved == []
    assert len(audit.recorded) == 1
    assert audit.recorded[0].action == AuditAction.CALENDAR_CONNECT
    assert audit.recorded[0].payload["status"] == "email_mismatch"
