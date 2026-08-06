from datetime import datetime
from enum import Enum

from app.modules.calendar.application.ports.driven.calendar_credential_repository import (
    CalendarCredentialRepositoryPort,
)
from app.modules.calendar.application.ports.driven.calendar_sync import CalendarSyncPort
from app.modules.calendar.application.ports.driven.calendar_sync_repository import CalendarSyncRepositoryPort
from app.modules.calendar.application.ports.driven.credential_vault import CredentialVaultPort
from app.modules.calendar.domain.calendar_credential import CalendarCredential
from app.modules.calendar.domain.calendar_event_mapping import CalendarEventMapping
from app.modules.calendar.domain.calendar_sync_record import CalendarSyncRecord
from app.modules.calendar.domain.idempotency import derive_idempotency_key
from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry

_DEFAULT_SUMMARY = "Kureha appointment"


class SyncOperation(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"


class SyncAppointmentToCalendar:
    def __init__(
        self,
        credential_repository: CalendarCredentialRepositoryPort,
        credential_vault: CredentialVaultPort,
        calendar_sync_repository: CalendarSyncRepositoryPort,
        calendar_sync_port: CalendarSyncPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._credential_repository = credential_repository
        self._credential_vault = credential_vault
        self._calendar_sync_repository = calendar_sync_repository
        self._calendar_sync_port = calendar_sync_port
        self._audit_log = audit_log

    async def execute(
        self,
        tenant_id: str,
        *,
        site_id: str,
        appointment_id: str,
        patient_id: str,
        starts_at: datetime,
        ends_at: datetime,
        summary: str = _DEFAULT_SUMMARY,
        operation: SyncOperation = SyncOperation.UPSERT,
    ) -> CalendarSyncRecord:
        idempotency_key = derive_idempotency_key(appointment_id)
        record = await self._calendar_sync_repository.get_or_create(
            tenant_id, site_id, appointment_id, idempotency_key=idempotency_key
        )

        encrypted = await self._credential_repository.get(tenant_id, patient_id)
        if encrypted is None:
            return await self._fail(tenant_id, appointment_id, reason="no_credential")
        if encrypted.is_revoked:
            return await self._fail(tenant_id, appointment_id, reason="revoked")

        try:
            refresh_token = (await self._credential_vault.decrypt(encrypted.secret)).decode("utf-8")
            cred = CalendarCredential(patient_id=patient_id, refresh_token=refresh_token, scope=encrypted.scope)

            if operation is SyncOperation.DELETE:
                target = record.google_event_id or idempotency_key
                result = await self._calendar_sync_port.delete_event(cred, target)
            else:
                mapping = CalendarEventMapping(
                    appointment_id=appointment_id,
                    idempotency_key=idempotency_key,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    summary=summary,
                )
                result = await self._calendar_sync_port.upsert_event(cred, mapping)
        except Exception as exc:  # noqa: BLE001 -- best-effort port call, see module docstring
            return await self._fail(tenant_id, appointment_id, reason=str(exc))

        if not result.ok:
            return await self._fail(tenant_id, appointment_id, reason=result.error or "unknown_error")

        updated = await self._calendar_sync_repository.mark_ok(
            tenant_id, appointment_id, google_event_id=result.google_event_id or idempotency_key
        )
        await self._audit_log.record(
            AuditEntry(
                tenant_id=tenant_id,
                site_id=site_id,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.CALENDAR_SYNC_OK,
                object_type="appointment",
                object_id=appointment_id,
                payload={"google_event_id": updated.google_event_id},
            )
        )
        return updated

    async def _fail(self, tenant_id: str, appointment_id: str, *, reason: str) -> CalendarSyncRecord:
        updated = await self._calendar_sync_repository.mark_failed(tenant_id, appointment_id, error=reason)
        await self._audit_log.record(
            AuditEntry(
                tenant_id=tenant_id,
                actor_type=AuditActorType.SYSTEM,
                action=AuditAction.CALENDAR_SYNC_FAILED,
                object_type="appointment",
                object_id=appointment_id,
                reason=reason,
            )
        )
        return updated
