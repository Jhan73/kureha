import dataclasses
from datetime import datetime, timezone

from app.modules.calendar.application.use_cases.sync_appointment_to_calendar import (
    SyncAppointmentToCalendar,
    SyncOperation,
)
from app.modules.calendar.domain.calendar_credential import EncryptedCredentialRecord
from app.modules.calendar.domain.calendar_event_mapping import CalendarSyncResult
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord, CalendarSyncStatus
from app.modules.calendar.domain.encrypted_secret import EncryptedSecret
from app.modules.calendar.domain.idempotency import derive_idempotency_key
from app.modules.governance.audit.domain.audit_entry import AuditAction

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
_APPOINTMENT_ID = "9c858901-8a57-4791-81fe-4c455b099bc9"


def _pending_record(**overrides) -> CalendarSyncRecord:
    defaults = dict(
        id="sync-1",
        tenant_id="t1",
        site_id="s1",
        appointment_id=_APPOINTMENT_ID,
        idempotency_key=derive_idempotency_key(_APPOINTMENT_ID),
        status=CalendarSyncStatus.PENDING,
        attempts=0,
        updated_at=_T0,
        google_event_id=None,
        last_error=None,
    )
    defaults.update(overrides)
    return CalendarSyncRecord(**defaults)


def _encrypted_record(*, revoked=False) -> EncryptedCredentialRecord:
    return EncryptedCredentialRecord(
        id="cred-1",
        tenant_id="t1",
        patient_id="p1",
        secret=EncryptedSecret(ciphertext=b"c", nonce=b"n" * 12, wrapped_dek=b"w", key_version=1),
        scope="scope",
        connected_at=_T0,
        revoked_at=_T0 if revoked else None,
    )


class _FakeCredentialRepository:
    def __init__(self, *, record: EncryptedCredentialRecord | None) -> None:
        self._record = record

    async def get(self, tenant_id, patient_id):
        return self._record

    async def save(self, tenant_id, patient_id, secret, *, scope):
        raise NotImplementedError

    async def revoke(self, tenant_id, patient_id):
        raise NotImplementedError


class _FakeCredentialVault:
    def __init__(self, *, plaintext: bytes = b"refresh-token") -> None:
        self._plaintext = plaintext

    async def encrypt(self, plaintext):
        raise NotImplementedError

    async def decrypt(self, secret) -> bytes:
        return self._plaintext


class _FakeCalendarSyncRepository:
    def __init__(self, *, existing: CalendarSyncRecord | None = None) -> None:
        self._record = existing or _pending_record()
        self.mark_ok_calls: list[dict] = []
        self.mark_failed_calls: list[dict] = []

    async def get_by_appointment(self, tenant_id, appointment_id):
        return self._record

    async def get_or_create(self, tenant_id, site_id, appointment_id, *, idempotency_key):
        return self._record

    async def mark_ok(self, tenant_id, appointment_id, *, google_event_id):
        self.mark_ok_calls.append({"appointment_id": appointment_id, "google_event_id": google_event_id})
        self._record = dataclasses.replace(
            self._record, status=CalendarSyncStatus.OK, google_event_id=google_event_id, last_error=None
        )
        return self._record

    async def mark_failed(self, tenant_id, appointment_id, *, error):
        self.mark_failed_calls.append({"appointment_id": appointment_id, "error": error})
        self._record = dataclasses.replace(
            self._record, status=CalendarSyncStatus.FAILED, last_error=error, attempts=self._record.attempts + 1
        )
        return self._record

    async def list_due_for_retry(self, tenant_id, *, max_attempts):
        raise NotImplementedError


class _FakeCalendarSyncPort:
    def __init__(self, *, result: CalendarSyncResult | None = None, raises: Exception | None = None) -> None:
        self._result = result or CalendarSyncResult(ok=True, google_event_id="evt-1")
        self._raises = raises
        self.upsert_calls: list = []
        self.delete_calls: list = []

    async def upsert_event(self, cred, mapping):
        self.upsert_calls.append((cred, mapping))
        if self._raises is not None:
            raise self._raises
        return self._result

    async def delete_event(self, cred, google_event_id):
        self.delete_calls.append(google_event_id)
        if self._raises is not None:
            raise self._raises
        return self._result


class _FakeAuditLog:
    def __init__(self) -> None:
        self.recorded: list = []

    async def record(self, entry) -> str:
        self.recorded.append(entry)
        return "audit-1"


_UNSET = object()


def _use_case(*, credential=_UNSET, sync_repo=None, sync_port=None, audit=None):
    credential = _encrypted_record() if credential is _UNSET else credential
    sync_repo = sync_repo or _FakeCalendarSyncRepository()
    sync_port = sync_port or _FakeCalendarSyncPort()
    audit = audit or _FakeAuditLog()
    use_case = SyncAppointmentToCalendar(
        _FakeCredentialRepository(record=credential),
        _FakeCredentialVault(),
        sync_repo,
        sync_port,
        audit,
    )
    return use_case, sync_repo, sync_port, audit


async def test_happy_path_marks_ok_and_audits() -> None:
    use_case, sync_repo, sync_port, audit = _use_case()

    result = await use_case.execute(
        "t1", site_id="s1", appointment_id=_APPOINTMENT_ID, patient_id="p1", starts_at=_T0, ends_at=_T1
    )

    assert result.status == CalendarSyncStatus.OK
    assert sync_repo.mark_ok_calls == [{"appointment_id": _APPOINTMENT_ID, "google_event_id": "evt-1"}]
    assert sync_port.upsert_calls[0][1].idempotency_key == derive_idempotency_key(_APPOINTMENT_ID)
    assert audit.recorded[0].action == AuditAction.CALENDAR_SYNC_OK


async def test_google_api_failure_result_marks_failed_and_never_raises() -> None:
    sync_port = _FakeCalendarSyncPort(result=CalendarSyncResult(ok=False, error="quota_exceeded"))
    use_case, sync_repo, _port, audit = _use_case(sync_port=sync_port)

    result = await use_case.execute(
        "t1", site_id="s1", appointment_id=_APPOINTMENT_ID, patient_id="p1", starts_at=_T0, ends_at=_T1
    )

    assert result.status == CalendarSyncStatus.FAILED
    assert sync_repo.mark_failed_calls == [{"appointment_id": _APPOINTMENT_ID, "error": "quota_exceeded"}]
    assert audit.recorded[0].action == AuditAction.CALENDAR_SYNC_FAILED


async def test_google_api_raised_exception_marks_failed_and_never_raises() -> None:
    sync_port = _FakeCalendarSyncPort(raises=TimeoutError("boom"))
    use_case, sync_repo, _port, _audit = _use_case(sync_port=sync_port)

    result = await use_case.execute(
        "t1", site_id="s1", appointment_id=_APPOINTMENT_ID, patient_id="p1", starts_at=_T0, ends_at=_T1
    )

    assert result.status == CalendarSyncStatus.FAILED
    assert "boom" in sync_repo.mark_failed_calls[0]["error"]


async def test_no_credential_connected_marks_failed_with_reason() -> None:
    use_case, sync_repo, sync_port, _audit = _use_case(credential=None)

    result = await use_case.execute(
        "t1", site_id="s1", appointment_id=_APPOINTMENT_ID, patient_id="p1", starts_at=_T0, ends_at=_T1
    )

    assert result.status == CalendarSyncStatus.FAILED
    assert sync_repo.mark_failed_calls[0]["error"] == "no_credential"
    assert sync_port.upsert_calls == []


async def test_revoked_credential_marks_failed_with_revoked_reason() -> None:
    use_case, sync_repo, sync_port, _audit = _use_case(credential=_encrypted_record(revoked=True))

    result = await use_case.execute(
        "t1", site_id="s1", appointment_id=_APPOINTMENT_ID, patient_id="p1", starts_at=_T0, ends_at=_T1
    )

    assert result.status == CalendarSyncStatus.FAILED
    assert sync_repo.mark_failed_calls[0]["error"] == "revoked"
    assert sync_port.upsert_calls == []


async def test_cancel_operation_calls_delete_event() -> None:
    use_case, sync_repo, sync_port, _audit = _use_case(
        sync_repo=_FakeCalendarSyncRepository(existing=_pending_record(google_event_id="evt-1"))
    )

    result = await use_case.execute(
        "t1",
        site_id="s1",
        appointment_id=_APPOINTMENT_ID,
        patient_id="p1",
        starts_at=_T0,
        ends_at=_T1,
        operation=SyncOperation.DELETE,
    )

    assert result.status == CalendarSyncStatus.OK
    assert sync_port.delete_calls == ["evt-1"]
    assert sync_port.upsert_calls == []
