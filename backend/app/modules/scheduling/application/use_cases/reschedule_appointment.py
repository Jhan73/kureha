"""`RescheduleAppointment` use case (design.md §5.3/§9, tasks.md task 7.3):
`authorize(ctx, action)` first, load the existing appointment and confirm it
is still active, then release its current slot and reserve the new one,
persist the move, and audit -- same "same transaction" contract as
`ScheduleAppointment` (ADR-3).

Does NOT invoke `RiskPolicy.evaluate_reschedule` -- see
`ScheduleAppointment`'s docstring: HITL routing on a professional-change
`risk_level` is the future graph's job (tasks.md Phase 11), resolved BEFORE
this use case runs. `new_availability_id`'s slot may carry a different
`professional_id` than the original appointment; that is a legitimate,
already-approved outcome by the time this executes.

Checks `StaffStatusPort.is_assignable` against the NEW slot's professional
(tasks.md task 8.4, spec `staff-registry` -> "Deactivated staff cannot be
scheduled") once the new slot is confirmed available, and BEFORE either
availability mutation (release the old slot / reserve the new one) --
mirrors `ScheduleAppointment`'s "no mutation before this check" contract."""

from app.modules.governance.audit.application.ports.driven.audit_log import AuditLogPort
from app.modules.governance.audit.domain.audit_entry import AuditAction, AuditActorType, AuditEntry
from app.modules.governance.rbac.application.use_cases.authorize_action import AuthorizeAction
from app.modules.scheduling.application.ports.driven.availability_repository import AvailabilityRepositoryPort
from app.modules.scheduling.application.ports.driven.scheduling_repository import SchedulingRepositoryPort
from app.modules.scheduling.application.ports.driven.staff_status_port import StaffStatusPort
from app.modules.scheduling.domain.appointment import Appointment
from app.modules.scheduling.domain.errors import (
    AppointmentNotFoundError,
    AvailabilitySlotNotFoundError,
    SlotUnavailableError,
    StaffNotAssignableError,
)
from app.shared_kernel.tenant_context import TenantContext

_ACTION = "appointment:reschedule"


class RescheduleAppointment:
    def __init__(
        self,
        authorize: AuthorizeAction,
        availability_repository: AvailabilityRepositoryPort,
        scheduling_repository: SchedulingRepositoryPort,
        audit_log: AuditLogPort,
        staff_status: StaffStatusPort,
    ) -> None:
        self._authorize = authorize
        self._availability_repository = availability_repository
        self._scheduling_repository = scheduling_repository
        self._audit_log = audit_log
        self._staff_status = staff_status

    async def execute(self, ctx: TenantContext, *, appointment_id: str, new_availability_id: str) -> Appointment:
        await self._authorize.execute(ctx, action=_ACTION)

        existing = await self._scheduling_repository.get_appointment(ctx.tenant_id, appointment_id)
        if existing is None:
            raise AppointmentNotFoundError(appointment_id)
        existing.ensure_active()

        new_slot = await self._availability_repository.get_slot(ctx.tenant_id, new_availability_id)
        if new_slot is None:
            raise AvailabilitySlotNotFoundError(new_availability_id)
        if not new_slot.is_available:
            raise SlotUnavailableError(f"slot {new_availability_id} is not available")

        if not await self._staff_status.is_assignable(ctx.tenant_id, new_slot.professional_id):
            raise StaffNotAssignableError(f"Professional {new_slot.professional_id} is not assignable")

        reserved = await self._availability_repository.reserve_slot(ctx.tenant_id, new_availability_id)
        await self._availability_repository.release_slot(ctx.tenant_id, existing.availability_id)

        updated = await self._scheduling_repository.reschedule_appointment(
            ctx.tenant_id,
            appointment_id,
            professional_id=reserved.professional_id,
            availability_id=new_availability_id,
            starts_at=reserved.starts_at,
            ends_at=reserved.ends_at,
        )

        await self._audit_log.record(
            AuditEntry(
                tenant_id=ctx.tenant_id,
                site_id=updated.site_id,
                actor_id=ctx.actor_id,
                actor_type=AuditActorType.USER,
                action=AuditAction.APPOINTMENT_RESCHEDULE,
                object_type="appointment",
                object_id=updated.id,
                payload={
                    "from_professional_id": existing.professional_id,
                    "to_professional_id": updated.professional_id,
                },
            )
        )
        return updated
