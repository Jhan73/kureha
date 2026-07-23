"""`CancelAppointment` use case (design.md §5.3/§9, tasks.md task 7.3):
`authorize(ctx, action)` first, load the existing appointment and confirm it
is still active, cancel it, release its `availability` slot back to the
pool, and audit -- same "same transaction" contract as `ScheduleAppointment`
(ADR-3).

Bulk cancellation (design.md §8.4's `RiskPolicy.evaluate_bulk_cancel`) is NOT
a separate use case here: a bulk cancel is the future `scheduling_agent`/
graph orchestration (tasks.md Phase 11) calling this single-appointment use
case N times after HITL approval, not a distinct DB operation this module
needs to expose."""

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.scheduling.application.ports.driven.availability_repository import AvailabilityRepositoryPort
from app.modules.scheduling.application.ports.driven.scheduling_repository import SchedulingRepositoryPort
from app.modules.scheduling.domain.appointment import Appointment
from app.modules.scheduling.domain.errors import AppointmentNotFoundError
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "appointment:cancel"


class CancelAppointment:
    def __init__(
        self,
        authorize: AuthorizeAction,
        availability_repository: AvailabilityRepositoryPort,
        scheduling_repository: SchedulingRepositoryPort,
        audit_log: AuditLogPort,
    ) -> None:
        self._authorize = authorize
        self._availability_repository = availability_repository
        self._scheduling_repository = scheduling_repository
        self._audit_log = audit_log

    async def execute(self, ctx: TenantContext, *, appointment_id: str) -> Appointment:
        await self._authorize.execute(ctx, action=_ACTION)

        existing = await self._scheduling_repository.get_appointment(ctx.tenant_id, appointment_id)
        if existing is None:
            raise AppointmentNotFoundError(appointment_id)
        existing.ensure_active()

        cancelled = await self._scheduling_repository.cancel_appointment(ctx.tenant_id, appointment_id)
        await self._availability_repository.release_slot(ctx.tenant_id, existing.availability_id)

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=cancelled.site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.APPOINTMENT_CANCEL,
                object_type="appointment",
                object_id=cancelled.id,
            )
        )
        return cancelled
