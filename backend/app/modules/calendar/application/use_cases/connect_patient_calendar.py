from app.modules.calendar.application.ports.driven.calendar_credential_repository import (
    CalendarCredentialRepositoryPort,
)
from app.modules.calendar.application.ports.driven.credential_vault import CredentialVaultPort
from app.modules.calendar.application.ports.driven.patient_email_lookup import PatientEmailLookupPort
from app.modules.calendar.domain.connect_calendar_result import CalendarConnected, CalendarEmailMismatch
from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "calendar:connect"


class ConnectPatientCalendar:
    def __init__(
        self,
        authorize: AuthorizeAction,
        patient_email_lookup: PatientEmailLookupPort,
        credential_vault: CredentialVaultPort,
        credential_repository: CalendarCredentialRepositoryPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._authorize = authorize
        self._patient_email_lookup = patient_email_lookup
        self._credential_vault = credential_vault
        self._credential_repository = credential_repository
        self._audit_log = audit_log

    async def execute(
        self,
        ctx: TenantContext,
        *,
        patient_id: str,
        google_email: str,
        refresh_token: str,
        scope: str,
    ) -> CalendarConnected | CalendarEmailMismatch:
        await self._authorize.execute(ctx, action=_ACTION)

        registered_email = await self._patient_email_lookup.get_registered_email(ctx.tenant_id, patient_id)
        if registered_email is not None and registered_email.lower() != google_email.lower():
            await self._audit_log.record(
                AuditEntry(
                    tenant_id=ctx.tenant_id,
                    site_id=ctx.site_id,
                    actor_id=ctx.actor_id,
                    actor_type=AuditActorType.USER,
                    action=AuditAction.CALENDAR_CONNECT,
                    object_type="calendar_credential",
                    object_id=patient_id,
                    payload={"status": "email_mismatch", "registered_email": registered_email, "google_email": google_email},
                )
            )
            return CalendarEmailMismatch(registered_email=registered_email, google_email=google_email)

        secret = await self._credential_vault.encrypt(refresh_token.encode("utf-8"))
        saved = await self._credential_repository.save(ctx.tenant_id, patient_id, secret, scope=scope)

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=ctx.site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.CALENDAR_CONNECT,
                object_type="calendar_credential",
                object_id=saved.id,
                payload={"status": "connected"},
            )
        )
        return CalendarConnected(credential_id=saved.id)
