"""`SendReminder` use case (design.md §5.3/§9, tasks.md task 7.3, spec
`appointment-scheduling` -> "Reminders and Confirmations"): `authorize(ctx,
action)` first, then attempt delivery through `ReminderChannelPort`.

**Uses `appointment:view`, not a dedicated `appointment:reminder` action.**
Design.md §5.1's action-key catalog only lists `appointment:{create,
reschedule,cancel,cancel_bulk,view}` -- there is no reminder-specific entry.
Sending a reminder does not mutate the appointment; it is closest in spirit
to reading/notifying about one already-visible appointment, so this reuses
`appointment:view` rather than inventing an ungoverned new action key.
Flagged here, not silently decided, in case a future review wants a
dedicated `appointment:reminder` action instead.

**Channel failures never propagate.** Spec: "Channel port failure does not
break scheduling flows" -- this use case treats BOTH a `False` return AND an
unhandled exception from `ReminderChannelPort.send` as "delivery failed,
still a successful use-case execution", per the port's own docstring. Every
attempt is logged to the audit trail regardless of outcome (spec: "Every
delivery attempt MUST be logged to the audit trail")."""

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.scheduling.application.ports.driven.reminder_channel import ReminderChannelPort
from app.modules.scheduling.application.ports.driven.scheduling_repository import SchedulingRepositoryPort
from app.modules.scheduling.domain.errors import AppointmentNotFoundError
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "appointment:view"


class SendReminder:
    def __init__(
        self,
        authorize: AuthorizeAction,
        scheduling_repository: SchedulingRepositoryPort,
        reminder_channel: ReminderChannelPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._authorize = authorize
        self._scheduling_repository = scheduling_repository
        self._reminder_channel = reminder_channel
        self._audit_log = audit_log

    async def execute(self, ctx: TenantContext, *, appointment_id: str) -> bool:
        await self._authorize.execute(ctx, action=_ACTION)

        appointment = await self._scheduling_repository.get_appointment(ctx.tenant_id, appointment_id)
        if appointment is None:
            raise AppointmentNotFoundError(appointment_id)

        payload: dict = {}
        try:
            delivered = await self._reminder_channel.send(appointment, patient_id=appointment.patient_id)
        except Exception as exc:  # noqa: BLE001 -- deliberately broad, see module docstring
            delivered = False
            payload["error"] = str(exc)

        payload = {"delivered": delivered, **payload}

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=appointment.site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.APPOINTMENT_REMINDER_SENT,
                object_type="appointment",
                object_id=appointment.id,
                payload=payload,
            )
        )
        return delivered
